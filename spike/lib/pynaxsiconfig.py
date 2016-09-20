from pynginxconfig import NginxConfig
import os
import pprint
import re
import sys
import json
from flask import current_app, flash



# Exemple usage
#x = NginxNaxsiConfig(current_app.config["NGINX_CFG_DIR"], "/home/bui/nbs-git/hosting-proxies/cerberhost_prod/",
#                     current_app.config["NGINX_CFG_DUMP"])
#x.process_arbo()



class NginxNaxsiConfig:
    #naxsi keywords
    nk_enabled = ['SecRulesEnabled']
    nk_learning = ['LearningMode']
    nk_denied = ['DeniedUrl']
    nk_checkrule = ['CheckRule']
    nk_basic = ['BasicRule']
    nk_main = ['MainRule']
    NAXSI_KEYWORDS = nk_basic+nk_learning+nk_denied+nk_checkrule+nk_basic+nk_main
    def __init__(self, nginx_dir=None, fake_root=None, outfile=None):
        """
        Dummy init, does nothing but store path to nginx config (from .conf)
        :return: None
        :arg: None
        """
        if nginx_dir is None:
            nginx_dir = current_app.config["NGINX_CFG_DIR"]
            print "nginx dir : {0}".format(nginx_dir)
        if outfile is None:
            outfile = current_app.config["NGINX_CFG_DUMP"]
            print "outfile : {0}".format(outfile)
        if fake_root is None:
            fake_root = current_app.config["NGINX_CFG_FAKE_ROOT"]

        self.site_enabled = nginx_dir
        self.fake_root = fake_root
        self.outfile = outfile
        print "config : site_enabled : {0}".format(self.site_enabled)
        print "config : fake_root : {0}".format(self.fake_root)
        print "config : outfile : {0}".format(self.outfile)


        #Current State
        self.parsed_results = {"default": []}
        self.default_location_config = {}
        self.current_file = None  # str
        self.current_fqdn = None  # str
        self.current_location = None  # str
        self.current_server_config = {}
        self.current_group = ""
        self.ssl_enabled = False

    def load_current_config(self):
        """
        Loads current config from json file
        :return dict:
        """
        cfg_dump = self.outfile
        try:
            x = open(cfg_dump, 'r')
        except:
            return {}
        all = json.loads(x.read())
        return all

    def new_server_name(self):
        """
        Called when a new server_name is encountered (stack current state)
        :arg: None
        :return: None
        """
        # init a new server block
        self.current_server_config[self.current_fqdn] = {"alt_fqdn": [], "locations": {}, "summary": {"auth": "off", "ssl": "off"}}
        self.current_location = None
        # ssl can be specified after or before server_name
        if self.ssl_enabled is True:
            self.current_server_config[self.current_fqdn]["summary"]["ssl"] = "on"
            self.ssl_enabled = False

    def new_location(self):
        """
        Called when a new location is encountered (stack current state)
        :arg: None
        :return: None
        """
        if self.current_fqdn is None:
            print "fqdn was none"
            self.current_fqdn = "_"
            self.current_server_config[self.current_fqdn] = {"alt_fqdn": [], "locations": {}, "summary": {"auth": "off", "ssl" : "off"}}
        self.current_server_config[self.current_fqdn]["locations"][self.current_location] = {"summary": {"naxsi": "off",
                                                                              "naxsi_learning": "off",
                                                                              "auth": "off"}, "checkrules": []}

    def parse_checkrule(self, block):
        """
        Parses a checkrule
        :param block:
        :return: a block (str) containing a checkrule
        """
        cr = {"score": 0,
              "label": "",
              "operator": "",
              "action": "",
              "fname": ""}
        #print "checkrule ! {0}".format(block)
        body = block.replace('\t', ' ').replace(' ', '')
        rz = re.match("^(['\"])(\$[^<>]+)([^0-9]+)([0-9]+)\\1([A-Z]+)$", body)
        if rz is None:
            print "didn't parse checkrule !!"
            pprint.pprint(body)
            sys.exit(1)
        cr["label"] = rz.group(2)
        cr["operator"] = rz.group(3)
        cr["score"] = rz.group(4)
        cr["action"] = rz.group(5)
        return cr

    def process_server_name(self, block):
        fqdn = ""
        alt_fqdn = []
        if type(block) == list:
            fqdn = block[0].replace('\t', ' ')
            fqdn = fqdn.split(' ')[0]
            alt_fqdn = fqdn.split(' ') + block[1:]
        elif type(block) == str:
            fqdn = block.replace('\t', ' ')
            fqdn = fqdn.split(' ')[0]
            alt_fqdn = fqdn.split(' ')
        else:
            print "unknown fqdn type : {0}".format(type(block))
            sys.exit(1)
        return fqdn, alt_fqdn

    def process_block(self, block, fname=None):
        if fname is not None:
            self.current_file = self.fake_root + fname
        #print "[FQDN:{0}|LOCATION:{1}|FILE:{2}] type :{3}".format(self.current_fqdn, self.current_location, self.current_file, type(block))
        #pprint.pprint(block)
        if type(block) == dict:
            if block["name"] == "include":
                self.process_block(block["value"], block["param"])
            elif block["name"] == "location":
                self.current_location = block["param"]
                self.new_location()
                self.process_block(block["value"])
            elif block["name"] == "server":
                if self.current_server_config != {}:
                    #pprint.pprint(block)
                    print "[x] appending {0} to group {1}".format(self.current_fqdn, self.current_group)
                    self.parsed_results[self.current_group].append(self.current_server_config)
                #try to guess a group name /sites-available/ /sites-enabled/
                self.current_group = "default"
                x = re.match(".*(/sites-available/|/sites-enabled/)([^/]+)/.*", self.current_file)
                if x:
                    self.current_group = x.group(2)
                if self.current_group not in self.parsed_results.keys():
                    self.parsed_results[self.current_group] = []
                self.current_server_config = {}
                self.current_fqdn = None
                self.current_location = None
                self.ssl_enabled = False
                self.process_block(block["value"])
        elif type(block) == tuple:
            if block[0] in self.NAXSI_KEYWORDS:
                if block[0] in ['SecRulesEnabled']:
                    self.current_server_config[self.current_fqdn]["locations"][self.current_location]["summary"]["naxsi"] = "on"
                    self.current_server_config[self.current_fqdn]["locations"][self.current_location]["summary"]["naxsi_path"] = self.current_file
                if block[0] in ['LearningMode']:
                    self.current_server_config[self.current_fqdn]["locations"][self.current_location]["summary"]["naxsi_learning"] = "on"
                    self.current_server_config[self.current_fqdn]["locations"][self.current_location]["summary"]["naxsi_learning_path"] = self.current_file
                if block[0] in ['CheckRule']:
                    cr = self.parse_checkrule(block[1])
                    cr["fname"] = self.current_file
                    self.current_server_config[self.current_fqdn]["locations"][self.current_location]["checkrules"].append(cr)
                    pass  # parse checkrule
            elif block[0] == "server_name":
                fqdn, alt_fqdn = self.process_server_name(block[1])
                self.current_fqdn = fqdn
                self.new_server_name()
                self.current_server_config[self.current_fqdn]["alt_fqdn"] = alt_fqdn
            elif block == ('deny', 'all') or block[0] == "auth_basic":
                if self.current_location is None:
                    self.current_server_config[self.current_fqdn]["summary"]["auth"] = "on"
                else:
                    self.current_server_config[self.current_fqdn]["locations"][self.current_location]["summary"]["auth"] = "on"
            elif block == ('ssl', 'on'):
                if self.current_fqdn not in self.current_server_config.keys():
                    self.ssl_enabled = True
                else:
                    self.current_server_config[self.current_fqdn]["summary"]["ssl"] = "on"
        elif type(block) == list:
            for bl in block:
                self.process_block(bl)
        
    def process_config_file(self, file):
        """
        Process one nginx/naxsi config, update current state
        :param file:
        :return:
        """
        p = NginxConfig()
        p.loadf(file, follow_includes=True, fake_root=self.fake_root)
        self.process_block(p.data, fname=file)

    def process_arbo(self):
        """
        Recursively parses dir/file of nginx/naxsi config
        :param:
        :return:
        """
        print "process arbo from : {0}".format(self.site_enabled)
        if self.site_enabled.endswith(".conf"):
            self.process_config_file(self.site_enabled)
        else:
            for root, dirs, files in os.walk(self.site_enabled):
                for file in files:
                    if file.endswith(".conf"):
                        print("Loading {0}".format(file))
                        self.process_config_file(root + '/' + file)
        self.write_json()

    def write_json(self):
        """
        Writes current state to a json file for spike ui
        :return:
        """
        z = open(self.outfile, "w+")
        z.write(json.dumps(self.parsed_results))
        z.close()


