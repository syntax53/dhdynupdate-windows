#!/usr/bin/env python3

# Copyright (c) 2016, Troy Telford
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are
# those of the authors and should not be interpreted as representing official
# policies, either expressed or implied.

import argparse
import configparser
import lockfile
import logging
import netifaces
import ipaddress
import os
if not os.name == 'nt':
    import daemon
import time
import sys

from dhdns import dhdns
def setup_logger(logfile, log_level, append):
    """Does logging setup, using python logging"""
    sFileMode = 'w'
    if append:
        sFileMode = 'a'
    
    try:
        logger = logging.basicConfig(
                 format='%(asctime)s %(levelname)s: %(message)s',
                 filename = logfile,
                 filemode=sFileMode,
                 level=log_level)
    except PermissionError as error:
        logging.critical("%s" % (error))
    except FileNotFoundError as error:
        logging.critical("It's likely your logfile path is invalid: %s" % (logfile))
        logging.critical("%s" % (error))
    except NameError as error:
        logging.critical("%s" % (error))
    except:
        logging.critical("Exception in setting up logging: %s" % (sys.exc_info()[0]))
        logging.critical("Could not set up logging! Exiting!")
        sys.exit(2)

previous_v4_address  = '127.0.0.1'
previous_v6_address  = '::1'
def setup_prev_addr_file(logfile):
    global previous_v4_address
    global previous_v6_address
    bWrite = False
    if os.path.isfile(logfile):
        with open(logfile, "r") as ins:
            lines = []
            for line in ins:
                lines.append(line)
                
        if len(lines) > 0:
            if len(lines[0]) > 6:
                previous_v4_address = lines[0].rstrip()
                logging.info("Previous V4 address loaded from file: %s" % (previous_v4_address))
            else:
                bWrite = True
        else:
            bWrite = True
        
        if len(lines) > 1:
            if len(lines[1]) > 3:
                previous_v6_address = lines[1].rstrip()
                logging.info("Previous V6 address loaded from file: %s" % (previous_v6_address))
    else:
        bWrite = True
        
    if bWrite:
        logging.debug("Writing new prev_addr_file: %s, %s" % (previous_v4_address, previous_v6_address))
        try:
            fo = open(logfile, "w")
            fo.write(previous_v4_address + "\n")
            fo.write(previous_v6_address + "\n")
            fo.close()
        except:
            logging.critical("Could not write previous address file: %s" % (logfile))
        
def main(argv=None):
    global previous_v4_address
    global previous_v6_address
    """Command line parser, begins DaemonContext for main loop"""
    if argv is None:
        argv = sys.argv
    # Command line parsing...
    cmd_parser = argparse.ArgumentParser()
    cmd_parser.add_argument("-d", "--daemon", action='store_true',
                            default=False, required=False,
                            dest="daemonize",
                            help="Execute %(prog)s as a dæmon (does not work on windows)")
    cmd_parser.add_argument("--debug", action='store', type=str,
                            default="WARNING", required=False,
                            dest="log_level", metavar="lvl",
                            help="Log Level, one of CRITICAL, ERROR, WARNING, INFO, DEBUG")
    cmd_parser.add_argument("-c", "--config", action='store',
                            type=str, default="DreamHost API Test Account",
                            required=False, metavar="config",
                            dest="config_name",
                            help="Configuration name")
    cmd_parser.add_argument("-e", "--external", action='store_true',
                            default=True, required=False,
                            dest="external_ip",
                            help="Use external address instead of internal")
    cmd_parser.add_argument("-a", "--append", action='store_true',
                            default=False, required=False,
                            dest="append_log",
                            help="Append log instead of overwrite log")
    args = cmd_parser.parse_args()

    # read configuration from file
    config = configparser.ConfigParser()
    try:
        config.read(os.path.dirname(os.path.realpath(sys.argv[0])) + "\dhdynupdate.conf")
    except:
        print("Error reading config file!")
        sys.exit(3)

    if args.log_level == "CRITICAL":
        log_level = 50
    elif args.log_level == "ERROR":
        log_level = 40
    elif args.log_level == "WARNING":
        log_level = 30
    elif args.log_level == "INFO":
        log_level = 20
    elif args.log_level == "DEBUG":
        log_level = 10
    else:
        log_level = 0

    # Get configuration settings
    try:
        supported_address_families = ("AF_INET", "AF_INET6")
        configured_interfaces = {}
        api_key = config[args.config_name]["api_key"]
        api_url = config["Global"]["api_url"]
        external_url = config["Global"]["external_url"]
        local_hostname = config[args.config_name]["local_hostname"]
        logfile = config["Global"]["log_file"]
        prev_addr_file = config["Global"]["prev_addr_file"]
        update_interval = int(config["Global"]["update_interval"])
        pid_file = config["Global"]["pidfile"]
        for addr_type in supported_address_families:
            interface = config["Global"][addr_type]
            if interface in netifaces.interfaces():
                configured_interfaces[addr_type] = interface
    except KeyError as error:
        # Technically, logger isn't "configured" -- it'll dump messages to the
        # console.
        print("Could not find configuration for %s" % (error))
#        logging.critical("Could not find configuration for %s" % (error))
        sys.exit(4)
    except:
        print("Exception in parsing configuration settings: %s"
                         % (sys.exc_info()[0]))
#        logging.critical("Exception in parsing configuration settings: %s"
#                         % (sys.exc_info()[0]))
        sys.exit(5)
    
    
    
#   When in doubt, do not run as a daemon. Daemon keeps stack traces from being
#   printed, and you're left wondering why the dæmon is quitting.
    if args.daemonize:
        if os.name == 'nt':
            logging.critical("Daemon not available on windows.")
        else:
            with daemon.DaemonContext(pidfile=lockfile.FileLock(pid_file)):
                # set up logging; it's much easier to just set it up within the
                # DaemonContext. Outside the daemoncontext requires a lot more work...
                setup_logger(logfile, log_level, args.append_log)
                logging.warn("Starting dhdynupdater...")
                setup_prev_addr_file(prev_addr_file)
                try:
                    pf = open(pid_file, 'w')
                    pf.write("%s\n" % (os.getpid()))
                    pf.close()
                except:
                    logging.critical("Exception in setting up pidfile: %s" % (sys.exc_info()[0]))
                    sys.exit(6)
                try:
                    dh_dns = dhdns(api_key, api_url, local_hostname, configured_interfaces, args.external_ip, external_url, previous_v4_address, previous_v6_address)
                except:
                    logging.critical("Exception in creating dh_dns: %s" % (sys.exc_info()[0]))
                while True:
                    logging.warn("Starting dhdynupdater main loop...")
                    try:
                        dh_dns.update_if_necessary()
                        time.sleep(update_interval)
                    except:
                        logging.critical("Exception in main loop: %s" % (sys.exc_info()[0]))
                        logging.warn("Closing dhdynupdater...")
                        logging.shutdown()
                        sys.exit(0)
                    logging.warn("looping dhdynupdater main loop...")
    else:
        setup_logger(logfile, log_level, args.append_log)
        logging.warn("Starting dhdynupdater...")
        setup_prev_addr_file(prev_addr_file)
        dh_dns = dhdns(api_key, api_url, local_hostname, configured_interfaces, args.external_ip, external_url, previous_v4_address, previous_v6_address)
        dh_dns.update_if_necessary()
        if str(dh_dns.previous_v4_address) != previous_v4_address or str(dh_dns.previous_v6_address) != previous_v6_address:
            try:
                fo = open(prev_addr_file, "w")
                fo.write(str(dh_dns.previous_v4_address) + "\n")
                fo.write(str(dh_dns.previous_v6_address) + "\n")
                fo.close()
            except:
                logging.critical("Could not write previous addresses to file: %s" % (logfile))

    logging.warn("Closing dhdynupdater...")
    logging.shutdown()

if __name__ == "__main__":
    main()

# vim: ts=4 sw=4 et
