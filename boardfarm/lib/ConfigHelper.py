import traceback
from json import load

import jsonschema
from boardfarm.exceptions import ConfigKeyError


def singleton(cls):
    instances = {}

    def getinstance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)

        return instances[cls]

    return getinstance


@singleton
class ConfigHelper(dict):
    """
    Accessing the board (station) configuration will soon go through this class.

    Getters and Setters will be here, rather than accessing the dict directly
    so that some control can be maintained.
    """

    def __getitem__(self, key):
        if key == "mirror":
            print("WARNING " * 9)
            print(
                'Support for calling config["mirror"] directly is going to be removed.'
            )
            print("Please change your test as soon as possible to this file transfer")
            print("in the proper way.")
            print("WARNING " * 9)

        if key in ("cm_cfg", "mta_cfg", "erouter_cfg"):
            print("ERROR: use of cm_cfg or mta_cfg in config object is deprecated!")
            print("Use board.cm_cfg or board.mta_cfg directly!")
            traceback.print_exc()
            raise ConfigKeyError

        if key in ("station"):
            print("ERROR: use get_station() not ['station']")
            traceback.print_exc()
            raise ConfigKeyError

        return dict.__getitem__(self, key)

    def update(self, config):
        """Important: used at board setup. Not to be invoked in tests"""
        super().update(config)
        return self

    def get_station(self):
        """Get station."""
        return dict.__getitem__(self, "station")


class SchemaValidator(object):
    """Validates the json files against the schema provided."""

    def __init__(self, schemapath, schemaname):
        """Instance initialisation."""
        with open(schemapath + schemaname, encoding="utf-8") as f:
            self.schema_file = load(f)

        self.resolver = jsonschema.RefResolver(
            base_uri="file://" + schemapath + "/", referrer=self.schema_file
        )

    def validate_json_schema(self, jsonpath, jsonname):
        """Validate json schema."""
        with open(jsonpath + jsonname, encoding="utf-8") as f:
            json_entry = load(f)
        try:
            jsonschema.validate(
                json_entry,
                self.schema_file,
                resolver=self.resolver,
                format_checker=jsonschema.FormatChecker(),
            )
            print("ok -", jsonname)
        except jsonschema.exceptions.ValidationError as error:
            print("not ok -", jsonname)
            print("Error: " + str(error) + " in " + str(error.path))

    def validate_json_schema_dict(self, dict):
        """Place holder to validate json dictionary."""
        pass
