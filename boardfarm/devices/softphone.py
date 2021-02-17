"""Class functions related to softphone software."""
from boardfarm.lib.dns import DNS
from boardfarm.lib.installers import install_pjsua


class SoftPhone(object):
    """Perform Functions related to softphone software."""

    model = "pjsip"
    profile = {}

    def __init__(self, *args, **kwargs):
        """Instance initialization."""
        self.args = args
        self.kwargs = kwargs
        self.own_number = self.kwargs.get("number", "3000")
        self.num_port = self.kwargs.get("num_port", "5060")
        self.config_name = "pjsip.conf"
        self.pjsip_local_url = kwargs.get("local_site", None)
        self.pjsip_prompt = ">>>"
        self.profile[self.name] = self.profile.get(self.name, {})
        softphone_profile = self.profile[self.name] = {}
        softphone_profile["on_boot"] = self.install_softphone
        self.dns = DNS(self, kwargs.get("options", {}), kwargs.get("aux_ip", {}))

    def __str__(self):
        """Magic method to return a printable string."""
        return "softphone"

    def install_softphone(self):
        """Install softphone from local url or from internet."""
        self.prefer_ipv4()
        install_pjsua(self, getattr(self, "pjsip_local_url", None))

    def phone_config(self, sipserver_ip):
        """Configure the soft phone.

        Arguments:
        sipserver_ip(str): ip of sip server
        """
        conf = (
            """(
        echo --local-port="""
            + self.num_port
            + """
        echo --id=sip:"""
            + self.own_number
            + """@"""
            + sipserver_ip
            + """
        echo --registrar=sip:"""
            + sipserver_ip
            + """
        echo --realm=*
        echo --username="""
            + self.own_number
            + """
        echo --password=1234
        echo --null-audio
        echo --max-calls=1
        echo --auto-answer=180
        )> """
            + self.config_name
        )
        self.sendline(conf)
        self.expect(self.prompt)

    def phone_start(self):
        """Start the soft phone.

        Note: Start softphone only when asterisk server is running to avoid failure
        """
        self.sendline("pjsua --config-file=" + self.config_name)
        self.expect(r"registration success, status=200 \(OK\)")
        self.sendline("/n")
        self.expect(self.pjsip_prompt)

    def dial(self, dial_number, receiver_ip):
        """Dial to the other phone.

        Arguments:
        dial_number(str): number to dial
        receiver_ip(str): ip of the receiver,it is mta ip the call is dialed to mta
        """
        self.sendline("/n")
        self.expect(self.pjsip_prompt)
        self.sendline("m")
        self.expect(r"Make call\:")
        self.sendline("sip:" + dial_number + "@" + receiver_ip)
        self.expect("Call [0-9]* state changed to CALLING")
        self.sendline("/n")
        self.expect(self.pjsip_prompt)

    def answer(self, exp_ans_msg=True):
        """To answer the incoming call in soft phone."""
        self.sendline("/n")
        self.expect(self.pjsip_prompt)
        if exp_ans_msg:
            pass
        self.sendline("a")
        self.expect(r"Answer with code \(100\-699\) \(empty to cancel\)\:")
        self.sendline("200")
        self.expect("Call [0-9]* state changed to CONFIRMED")
        self.sendline("/n")
        self.expect(self.pjsip_prompt)

    def hangup(self):
        """To hangup the ongoing call."""
        self.sendline("/n")
        self.expect(self.pjsip_prompt)
        self.sendline("h")
        self.expect("DISCON")
        self.sendline("/n")
        self.expect(self.pjsip_prompt)

    def reinvite(self):
        """To re-trigger the Invite message"""
        self.sendline("\n")
        self.expect(self.pjsip_prompt)
        self.sendline("v")
        self.expect("Sending re-INVITE on call [0-9]*")
        self.expect("SDP negotiation done: Success")
        self.sendline("\n")
        self.expect(self.pjsip_prompt)

    def phone_kill(self):
        """To kill the pjsip session."""
        # De-Registration is required before quit a phone and q will handle it
        self.sendline("q")
        self.expect(self.prompt)

    def validate_state(self, msg):
        """Verify the message to validate the status of the call

        :param msg: The message to expect on the softphone container
        :type msg: string
        :example usage:
           validate_state('INCOMING') to validate an incoming call.
           validate_state('Current call id=<call_id> to <sip_uri> [CONFIRMED]') to validate call connected.
        :return: boolean True if success
        :rtype: Boolean
        """
        self.sendline("/n")
        self.expect(self.pjsip_prompt)
        if msg == "INCOMING":
            msg = "180 Ringing"
        self.expect(msg)
        self.expect(self.pjsip_prompt)
        return True
