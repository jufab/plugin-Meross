#!/usr/bin/python3

import argparse
import asyncio
import json
import logging
import os
import pprint
import sys
from datetime import datetime, timedelta

from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager
from meross_iot.model.enums import OnlineStatus, Namespace
from meross_iot.model.http.exception import BadLoginException

debug = False

if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")

# Get Python version
pver = str(sys.version_info.major) + '.' + str(sys.version_info.minor)

# Add Meross-iot lib to Pythonpath
current_dir = os.path.normpath(os.path.dirname(os.path.abspath(os.path.realpath(sys.argv[0]))))

# Var dir
var_dir = current_dir

# Meross lib
meross_root_logger = logging.getLogger("meross_iot")
meross_root_logger.setLevel(logging.ERROR)

# data files
conffile = os.path.join(var_dir, 'config.ini')


# ---------------------------------------------------------------------


class WriteLog:
    def __init__(self):
        self.debug = debug

    def p(self, txt):
        if self.debug:
            print(txt)
        return


# ---------------------------------------------------------------------


def read_config(conffile=conffile):
    """ Read config (secrets) """
    import configparser
    config = configparser.ConfigParser()
    try:
        config.read(conffile)
        email = config.get('secret', 'email')
        password = config.get('secret', 'password')
    except:
        print("""
>>>> Error : wrong file 'config.ini' ! Please create this file with this contents :

[secret]
email = your-meross-email-account
password = your-meross-password

""")
        sys.exit(1)
    return email, password


# ---------------------------------------------------------------------
def exit(txt=""):
    print(txt)
    sys.exit(1)


# ---------------------------------------------------------------------
async def refresh_one_device(device):
    """ Connect to Meross Cloud and refresh only the device 'device' """
    await device.async_update()
    d = dict({
        'name': device.name,
        'uuid': device.uuid,
        'ip': '',
        'mac': '',
        'online': device.online_status == OnlineStatus.ONLINE,
        'type': device.type,
        'firmversion': device.firmware_version,
        'hardversion': device.hardware_version,
    })

    if device.online_status == OnlineStatus.ONLINE:
        data = device.abilities
        if debug:
            pprint.pprint(data)
        try:
            d['ip'] = data['all']['system']['firmware']['innerIp']
        except:
            pass

        try:
            d['mac'] = data['all']['system']['hardware']['macAddress']
        except:
            pass

        # on/off status
        onoff = []
        try:
            onoff = device.is_on()
        except:
            pass
        d['onoff'] = onoff

        # Current power
        try:
            electricity = await device.async_get_instant_metrics()
            d['power'] = electricity.power
            d['voltage'] = electricity.voltage
            d['current'] = electricity.current
        except:
            d['power'] = -1
            d['voltage'] = -1
            d['current'] = -1

        # Historical consumption
        # print (dir(device) )
        d['consumption'] = []  # on decide de ne pas la stocker
        try:
            # pprint.pprint (device.get_power_consumption())
            l_consumption = await device.async_get_daily_power_consumption()
            # Yesterday consumption
            today = datetime.today()
            yesterday = (today - timedelta(1)).strftime("%Y-%m-%d")
            d['consumption_yesterday'] = 0

            for c in l_consumption:
                dateconso = c['date'].strftime("%Y-%m-%d")
                if dateconso == yesterday:
                    try:
                        d['consumption_yesterday'] = c['total_consumption_kwh']
                    except:
                        d['consumption_yesterday'] = 0
                    break

        except:
            d['consumption_yesterday'] = 0
            # l_consumption = []

    return d


# ---------------------------------------------------------------------
# def event_handler(eventobj):
# TODO: handle events in plugin
#
# if eventobj.event_type == MerossEventType.DEVICE_ONLINE_STATUS:
#     # print("Device online status changed: %s went %s" % (eventobj.device.name, eventobj.status))
#     pass
#
# elif eventobj.event_type == MerossEventType.DEVICE_SWITCH_STATUS:
#     # print("Switch state changed: Device %s (channel %d) went %s" % (eventobj.device.name, eventobj.channel_id, eventobj.switch_state))
# elif eventobj.event_type == MerossEventType.CLIENT_CONNECTION:
#     # print("MQTT connection state changed: client went %s" % eventobj.status)
#
#     # TODO: Give example of reconnection?
#
# elif eventobj.event_type == MerossEventType.GARAGE_DOOR_STATUS:
#     # print("Garage door is now %s" % eventobj.door_state)
#
# elif eventobj.event_type == MerossEventType.THERMOSTAT_MODE_CHANGE:
#     # print("Thermostat %s has changed mode to %s" % (eventobj.device.name, eventobj.mode))
#
# elif eventobj.event_type == MerossEventType.THERMOSTAT_TEMPERATURE_CHANGE:
#     # print("Thermostat %s has revealed a temperature change: %s" % (eventobj.device.name, eventobj.temperature))
#
# else:
# print("Unknown event!")

# ---------------------------------------------------------------------
async def connect_and_refresh_all(email, password):
    """ Connect to Meross Cloud and refresh all devices and informations """
    try:
        # Initiates the Meross Cloud Manager. This is in charge of handling the communication with the remote endpoint
        http_api_client = await MerossHttpClient.async_from_user_password(email=email, password=password)
        # Setup and start the device manager
        manager = MerossManager(http_client=http_api_client)
    except BadLoginException:
        exit(f"<F> Error : can't connect to Meross Cloud ! Please verify Internet connection, email and password !")
    except BaseException as base:
        exit(f"Error : {base}")
    # Retrieves the list of supported devices
    await manager.async_init()
    # Discover devices.
    await manager.async_device_discovery()
    devices = manager.find_devices()

    # Build dict of devices informations
    d_devices = {}

    for num in range(len(devices)):
        if debug:
            print(50 * '=' + '\nnum=', num)
        device = devices[num]
        d = await refresh_one_device(device=device)

        uuid = device.uuid
        d_devices[uuid] = d

    if debug:
        pprint.pprint(d_devices)

    # Close the manager and logout from http_api
    manager.close()
    await http_api_client.async_logout()

    return d_devices


# ---------------------------------------------------------------------


async def connect_and_set_on_off(devices, email, password, name=None, uuid=None, mac=None, action='on', channel=0):
    """ Connect to Meross Cloud and set on or off a smartplug """
    if mac and not name and not uuid:
        exit("<F> Error : not implemented !")
    if not name and not uuid and not mac:
        exit("<F> Error : need at least 'name', 'uuid' or 'mac' parameter to set on or off a smartplug !")

    """ Connect to Meross Cloud and refresh all devices and informations """
    try:
        # Initiates the Meross Cloud Manager. This is in charge of handling the communication with the remote endpoint
        http_api_client = await MerossHttpClient.async_from_user_password(email=email, password=password)
        # Setup and start the device manager
        manager = MerossManager(http_client=http_api_client)
    except BadLoginException:
        exit(f"<F> Error : can't connect to Meross Cloud ! Please verify Internet connection, email and password !")
    except BaseException as base:
        exit(f"Error : {base}")
    # Retrieves the list of supported devices
    await manager.async_init()
    # Discover devices.
    await manager.async_device_discovery()
    device = None
    if uuid is not None:
        device = manager.find_devices(device_uuids=uuid)[0]
    elif name is not None:
        device = manager.find_devices(device_name=name)[0]
    if device is not None:
        await device.async_update()
        if device.online_status == OnlineStatus.ONLINE:
            try:
                if action == 'on':
                    await device.async_turn_on(int(channel))
                else:
                    await device.async_turn_off(int(channel))
            except:
                print("Unexpected error:", sys.exc_info()[0])

    devices[device.uuid] = await refresh_one_device(device)

    # Close the manager and logout from http_api
    manager.close()
    await http_api_client.async_logout()

    return devices


# ---------------------------------------------------------------------


def get_by_name(d_devices, name):
    """ Find a Meross Smartplug from name """
    for k in d_devices.keys():
        if (d_devices[k]['name'] == name):
            return d_devices[k]
    return {}


# ---------------------------------------------------------------------


def get_by_uuid(d_devices, uuid):
    """ Find a Meross Smartplug from uuid """
    for k in d_devices.keys():
        if (d_devices[k]['uuid'] == uuid):
            return d_devices[k]
    return {}


# ---------------------------------------------------------------------


def get_by_mac(d_devices, mac):
    """ Find a Meross Smartplug from MAC """
    for k in d_devices.keys():
        if (d_devices[k]['mac'] == mac):
            return d_devices[k]
    return {}


# ---------------------------------------------------------------------
if __name__ == '__main__':

    # Arguments
    parser = argparse.ArgumentParser(description='Meross Python lib for Nextdom')
    parser.add_argument('--refresh', action="store_true", default=False)
    parser.add_argument('--uuid', action="store", dest="uuid")
    parser.add_argument('--name', action="store", dest="name")
    parser.add_argument('--mac', action="store", dest="mac")
    parser.add_argument('--channel', action="store", dest="channel", default="0")
    parser.add_argument('--set_on', action="store_true", default=False)
    parser.add_argument('--set_off', action="store_true", default=False)
    parser.add_argument('--show_power', action="store_true", default=False)
    parser.add_argument('--show_yesterday', action="store_true", default=False)
    parser.add_argument('--show', action="store_true", default=False)
    parser.add_argument('--email', action="store", dest="email")
    parser.add_argument('--password', action="store", dest="password")
    parser.add_argument('--config', action="store", dest="config")
    parser.add_argument('--debug', action="store_true", default=False)

    args = parser.parse_args()
    # print(args)

    # WriteLog
    l = WriteLog()
    l.debug = args.debug

    # Refresh all devices and informations from local file
    refresh = True

    # Get email / password (only if necessary : refresh or action)
    if args.refresh or refresh or args.set_on or args.set_off:
        email = None
        password = None
        # Get from commandline argument
        if args.email and args.password:
            email = args.email
            password = args.password
        # Get from config file (commandline argument)
        elif args.config:
            if not os.isfile(args.config):
                exit("<F> Error : can't read '%s' config file!" % args.config)
            else:
                try:
                    email, password = read_config(conffile=args.config)
                except:
                    exit("<F> Error : can't read '%s' config file!" % args.config)
        # Get from local config file
        elif os.path.isfile(conffile):
            try:
                email, password = read_config(conffile=conffile)
            except:
                exit("<F> Error : can't read '%s' config file!" % args.config)

        # If not defined --> error
        if not email or not password:
            exit("<F> Error : Can't get email and password !")
    d_devices = {}
    # Connect to Meross Cloud and Refresh
    if args.refresh:
        d_devices = asyncio.run(connect_and_refresh_all(email, password))
    # Set on / off
    if args.set_on:
        d_devices = asyncio.run(connect_and_set_on_off(devices=d_devices, email=email, password=password,
                                           name=args.name, uuid=args.uuid, mac=args.mac,
                                           action='on', channel=args.channel))
    if args.set_off:
        d_devices = asyncio.run(connect_and_set_on_off(devices=d_devices, email=email, password=password,
                                           name=args.name, uuid=args.uuid, mac=args.mac,
                                           action='off', channel=args.channel))

    # Find the Smartplug
    SP = None
    if args.name:
        if debug:
            print("<I> Getting informations for Smartplug named '%s' ..." % args.name)
        SP = get_by_name(d_devices=d_devices, name=args.name)
    elif args.uuid:
        if debug:
            print("<I> Getting informations for Smartplug with uuid '%s' ..." % args.uuid)
        SP = get_by_uuid(d_devices=d_devices, uuid=args.uuid)
    elif args.mac:
        if debug:
            print("<I> Getting informations for Smartplug with MAC '%s' ..." % args.mac)
        SP = get_by_mac(d_devices=d_devices, mac=args.mac)
    else:
        SP = d_devices

    # Return only Power value
    if args.show_power:
        print(str(int(SP['power'])))

    # Return only yesterday Consumption value
    elif args.show_yesterday:
        print(str(int(SP['consumption_yesterday'])))

    # Return the JSON output
    elif args.show:
        # pprint.pprint(SP)
        # jsonarray = json.dumps(SP)
        if args.name or args.uuid or args.mac:
            d = dict({SP['uuid']: SP})
        else:
            d = d_devices
        jsonarray = json.dumps(d, indent=4, sort_keys=True)
        print(jsonarray)
