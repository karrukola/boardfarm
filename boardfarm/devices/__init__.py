"""This directory contains classes for connecting to and controlling \
devices over a network."""

import importlib
import inspect
import logging
import os
import pkgutil
import re
import traceback
from collections import UserList
from typing import Dict, Optional

import pexpect
import termcolor

import boardfarm
from boardfarm.exceptions import BftNotSupportedDevice, ConnectionRefused
from boardfarm.lib.DeviceManager import device_manager
from boardfarm.tests_wrappers import check_plugin_for_probe_devices

# TODO: this probably should not the generic device
from . import openwrt_router

logger = logging.getLogger("bft")

# Will be populate on runtime
# bft::connect_to_devices for each board will set a device manager instance
manager: Optional[device_manager] = None


class DeviceMappings:
    dev_mappings: Dict = {}
    dev_sw_mappings: Dict = {}


@check_plugin_for_probe_devices(DeviceMappings)
def probe_devices():
    """Dynamically find all devices classes across all boardfarm projects."""
    all_boardfarm_modules = dict(boardfarm.plugins)
    all_boardfarm_modules["boardfarm"] = importlib.import_module("boardfarm")

    all_mods = []

    # Loop over all modules to import their devices
    for modname in all_boardfarm_modules:
        bf_module = all_boardfarm_modules[modname]
        device_module = pkgutil.get_loader(".".join([bf_module.__name__, "devices"]))
        if device_module:
            all_mods += boardfarm.walk_library(
                device_module.load_module(),
                filter_pkgs=["base_devices", "connections", "platform"],
            )

    for module in all_mods:
        device_mappings[module] = []
        for thing_name in dir(module):
            thing = getattr(module, thing_name)
            if inspect.isclass(thing) and hasattr(thing, "model"):
                # thing.__module__ prints the module name where it is defined
                # this name needs to match the current module we're scanning.
                # else we skip
                if thing.__module__ == module.__name__:
                    device_mappings[module].append(thing)


device_mappings = DeviceMappings.dev_mappings
device_sw_mappings = DeviceMappings.dev_sw_mappings


def check_for_cmd_on_host(cmd, msg=None):
    """Print an error message with a suggestion on how to install the command."""
    from boardfarm.lib.common import cmd_exists

    if not cmd_exists(cmd):
        logger.error(
            termcolor.colored(
                "\nThe  command '"
                + cmd
                + "' is NOT installed on your system. Please install it.",
                None,
                attrs=["bold"],
            )
        )
        if msg is not None:
            logger.info(cmd + ": " + msg)
        import sys

        if sys.platform == "linux2":
            import platform

            if "Ubuntu" in platform.dist() or "debian" in platform.dist():
                logger.error(
                    "To install run:\n\tsudo apt install <package with " + cmd + ">"
                )
                exit(1)
        logger.debug("To install refer to your system SW app installation instructions")


class _prompt(UserList, list):
    """Check all currently instantiated devices and returns a read-only list.

    This used to be a static list, but since we track devices more closely we can
    now dynamically create this list of prompts. It checks all currently instanstiated
    devices and returns a read-only list
    """

    def get_prompts(self):
        ret = []

        for d in manager:
            for p in getattr(d, "prompt", []):
                if p not in ret:
                    ret.append(p)

        return ret

    data = property(get_prompts, lambda *args: None)


prompt = _prompt()


def bf_node(cls_list, model, device_mgr, **kwargs):
    """Return an instance of a dynamically created class.

    ...
    The class is created using type of classname, superclasses, attributes_dict method
    :param cls_list: Superclasses for the dynamically created class
    :type cls_list: list
    :param ``**kwargs``: used for defining attributes of the dynamic class

    ...
    """
    cls_name = "_".join([cls.__name__ for cls in cls_list])
    cls_members = []
    """Need to ensure that profile does not have members which override
    the base_cls implementation."""
    temp = []
    for cls in cls_list:
        members = [
            attr
            for attr in cls.__dict__
            if not attr.startswith("__")
            and not attr.endswith("__")
            and attr not in ("model", "prompt", "profile")
        ]
        common = list(set(members) & set(cls_members))
        if len(common) > 0:
            raise Exception(
                "Identified duplicate class members %s between classes  %s"
                % (str(common), str(cls_list[: cls_list.index(cls) + 1]))
            )

        cls_members.extend(members)
        temp.append(cls)

    cls_list = temp
    cls_name = "_".join([cls.__name__ for cls in cls_list])

    def __init__(self, *args, **kwargs):
        for cls in cls_list:
            cls.__init__(self, *args, **kwargs)

    ret = type(cls_name, tuple(cls_list), {"__init__": __init__})(
        model, mgr=device_mgr, **kwargs
    )
    ret.target = kwargs

    return ret


def get_device(model, device_mgr, **kwargs):
    """Create a class instance for a device.

    These are connected to the device Under Test (DUT) board.
    """
    profile = kwargs.get("profile", {})
    override = kwargs.pop("override", False)
    plugin = kwargs.pop("plugin_device", False)
    cls_list = []
    profile_list = []
    for _device_file, devs in device_mappings.items():
        for dev in devs:
            if "model" in dev.__dict__:
                attr = dev.__dict__["model"]

                if type(attr) is str and model == attr:
                    cls_list.append(dev)
                elif type(attr) is tuple and model in attr:
                    cls_list.append(dev)

                profile_exists = False
                if len(profile) > 0:
                    if type(attr) is str and attr in profile:
                        profile_exists = True
                        profile_kwargs = profile[attr]
                    elif type(attr) is tuple and len(set(attr) & set(profile)) == 1:
                        profile_exists = True
                        profile_kwargs = profile[list(set(attr) & set(profile))[0]]

                if profile_exists:
                    if dev not in cls_list:
                        profile_list.append(dev)
                    else:
                        logger.warning(f"Skipping duplicate device type: {attr}")
                        continue
                    common_keys = set(kwargs) & set(profile_kwargs)
                    if len(common_keys) > 0:
                        logger.warning(
                            "Identified duplicate keys in profile and base device : %s"
                            % str(list(common_keys))
                        )
                        logger.warning("Removing duplicate keys from profile!")
                        for i in list(common_keys):
                            profile_kwargs.pop(i)
                    kwargs.update(profile_kwargs)

    try:
        # to ensure profile always initializes after base class.
        cls_list.extend(profile_list)
        if len(cls_list) == 0:
            raise BftNotSupportedDevice(f"Unable to spawn instance of model: {model}")
        ret = bf_node(cls_list, model, device_mgr, **kwargs)

        # Allow a device to initialize without registering to device_mgr
        if device_mgr is not None:
            device_mgr._add_device(ret, override, plugin)
        return ret
    except BftNotSupportedDevice:
        raise
    except ConnectionRefused:
        raise
    except pexpect.EOF:
        msg = (
            "Failed to connect to a %s, unable to connect (in use) or possibly misconfigured"
            % model
        )
        raise Exception(msg)
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e))

    return None


def board_decider(model, **kwargs):
    """Create class instance for the Device Under Test (DUT) board."""
    if any("conn_cmd" in s for s in kwargs):
        if any("kermit" in s for s in kwargs["conn_cmd"]):
            check_for_cmd_on_host(
                "kermit",
                "telnet equivalent command. It has lower CPU usage than telnet,\n\
and works exactly the same way (e.g. kermit -J <ipaddr> [<port>])\n\
You are seeing this message as your configuration is now using kermit instead of telnet.",
            )
    dynamic_dev = get_device(model, **kwargs)
    if dynamic_dev is not None:
        return dynamic_dev

    # Default for all other models
    logger.warning(f"\nWARNING: Unknown board model '{model}'.")
    logger.warning(
        "Please check spelling, your environment setup, or write an appropriate class "
        "to handle that kind of board."
    )

    if len(boardfarm.plugins) > 0:
        logger.info("The following boardfarm plugins are installed.")
        logger.info("Do you need to update them or install others?")
        logger.info("\n".join(boardfarm.plugins))
    else:
        logger.error("No boardfarm plugins are installed, do you need to install some?")

    if "BFT_CONFIG" in os.environ:
        logger.info(f"\nIs this correct? BFT_CONFIG={os.environ['BFT_CONFIG']}\n")
    else:
        logger.error("No BFT_CONFIG is set, do you need one?")

    return openwrt_router.OpenWrtRouter(model, **kwargs)


def get_device_mapping_class(sw: str):
    for k, v in device_sw_mappings.items():
        if type(v) is not list:
            v = [v]
        for _p in v:
            pattern = re.compile(_p)
            if re.match(pattern, sw):
                return k
    return None
