"""Routines for interacting with IOTile cloud from the command line
"""

from io import BytesIO
import requests
import getpass
import time
import datetime
from dateutil.tz import tzutc
import dateutil.parser

from iotile_cloud.api.connection import Api
from iotile_cloud.api.exceptions import RestHttpBaseException, HttpNotFoundError
from iotile.core.dev.registry import ComponentRegistry
from iotile.core.dev.config import ConfigManager
from iotile.core.exceptions import ArgumentError, ExternalError
from iotile.core.utilities.typedargs import context, param, return_type, annotated, type_system
from utilities import device_id_to_slug

@context("IOTileCloud")
class IOTileCloud(object):
    """High level routines for interacting with IOTile cloud.

    Normally, you can create one of these objects with no arguments
    and the iotile.cloud server and authentication details will
    be pulled from the ComponentRegistry.  However, you can force
    a specific domain by passing the optional domain arguments.

    If there are no stored credentials in ComponentRegistry, the
    user will be prompted for a password on the command line IF
    the session is interactive, otherwise __init__ will fail.

    Args:
        domain (str): Optional server domain.  If not specified,
            the default will be whatever is stored in the registry
        username (str): Optional username to force the user to use
            if they don't have stored credentials
    """

    def __init__(self, domain=None, username=None):
        reg = ComponentRegistry()
        conf = ConfigManager()

        if domain is None:
            domain = conf.get('cloud:server')

        self.api = Api(domain=domain)

        try:
            token = reg.get_config('arch:cloud_token')
            self.api.set_token(token)
        except ArgumentError:
            # If we are interactive, try to get the user to login for a single
            # session rather than making them call link_cloud to store a cloud token
            if type_system.interactive:
                if username is None:
                    username = raw_input("Please enter your (%s) username: " % domain)

                password = getpass.getpass('Please enter the (%s) password for %s: ' % (domain, username))
                ok_resp = self.api.login(email=username, password=password)

                if not ok_resp:
                    raise ExternalError("Could not login to %s as user %s" % (domain, username))
            else:
                raise ExternalError("No stored iotile cloud authentication information", suggestion='Call iotile config link_cloud with your iotile cloud username and password')

        self.token = self.api.token

    def _build_device_slug(self, device_id):
        idhex = "{:04x}".format(device_id)

        return "d--0000-0000-0000-{}".format(idhex)

    def _build_streamer_slug(self, device_id, streamer_id):
        idhex = "{:04x}".format(device_id)
        streamer_hex = "{:04x}".format(streamer_id)

        return "t--0000-0000-0000-{}--{}".format(idhex, streamer_hex)

    @param("device_id", "integer", desc="ID of the device that we want information about")
    @return_type("basic_dict")
    def device_info(self, device_id):
        """Query information about a device by its device id
        """

        slug = self._build_device_slug(device_id)

        try:
            dev = self.api.device(slug).get()
        except HttpNotFoundError:
            raise ArgumentError("Device does not exist in cloud database", device_id=device_id, slug=slug)

        return dev

    @param("fleet_id", "integer", desc="Id of the fleet we want to retrieve")
    @return_type("basic_dict")
    def get_fleet(self, fleet_id):
        """ Returns the devices in the given fleet"""
        api = self.api
        if (fleet_id > pow(16,12) or fleet_id < 0):
            raise ArgumentError("Fleet id outside of bounds")
        slug = "g--" + device_id_to_slug(fleet_id)[8:]
        try :
            return api.fleet(slug).devices.get()
        except HttpNotFoundError:
            raise ArgumentError("Fleet does not exist in cloud database", fleet_id=fleet_id, slug=slug)

    @param("device_id", "integer", desc="Id of the device whose fleet we want to retrieve")
    @return_type("list(string)")
    def get_fleet_ids_from_device(self, device_id):
        """ Returns the fleets the device is in"""
    @return_type("basic_dict")
    def get_whitelist(self, device_id):
        """ Returns the whitelist associated with the given device_id if any"""
        api = self.api
        slug = device_id_to_slug(device_id)
        try:
            fleets = api.fleet.get(device=slug)['results']
        except HttpNotFoundError:
            raise ExternalError("Could not find the right URL. Are fleets enabled ?")

        if not fleets:
            # This is to be expected for devices set to take data from all project, or any device.
            raise ExternalError("The device isn't in any network !")

        out = {}
        for fleet in fleets:
            if fleet['is_network']:
                devices = self.get_fleet(fleet['id'])['results']
                print(devices)
                if len([i for i in devices if i['device'] == slug and i['is_access_point']]):
                    for device in devices:
                        if device['device'] not in out and device['device'] != device_id_to_slug(device_id):
                            out[device.pop('device')] = device
        return out

    @param("max_slop", "integer", desc="Optional max time difference value")
    @return_type("bool")
    def check_time(self, max_slop = 300):
        """ Check if current system time is consistent with iotile.cloud time"""
        cloud_time = requests.get('https://iotile.cloud/api/v1/server/').json().get('now', None)
        if cloud_time is None:
            raise DataError("No date header returned from iotile.cloud")

        curtime = datetime.datetime.now(tzutc())
        delta = dateutil.parser.parse(cloud_time) - curtime
        delta_secs = delta.total_seconds()

        return abs(delta_secs) < max_slop

    @param("device_id", "integer", desc="ID of the device that we want information about")
    @param("new_sg", "string", desc="The new sensor graph id that we want to load")
    def set_sensorgraph(self, device_id, new_sg):
        """The the cloud's sensor graph id that informs what kind of device this is
        """

        slug = self._build_device_slug(device_id)

        patch = {'sg': new_sg}

        try:
            self.api.device(slug).patch(patch)
        except RestHttpBaseException, exc:
            if exc.response.status_code == 400:
                raise ArgumentError("Error setting sensor graph, invalid value", value=new_sg, error_code=exc.response.status_code)
            else:
                raise ExternalError("Error calling method on iotile.cloud", exception=exc, response=exc.response.status_code)

    @param("project_id", "string", desc="Optional ID of the project to download a list of devices from")
    @return_type("list(integer)")
    def device_list(self, project_id=None):
        """Download a list of all device IDs or device IDs that are members for a specific project."""

        if project_id:
            devices = self.api.device.get(project=project_id)
        else:
            devices = self.api.device.get()

        ids = [device['id'] for device in devices['results']]
        return ids

    @param("device_id", "integer", desc="ID of the device that we want information about")
    @param("clean", "bool", desc="Also clean old stream data for this device")
    def unclaim(self, device_id, clean=True):
        """Unclaim a device that may have previously been claimed
        """

        slug = self._build_device_slug(device_id)

        payload = {'clean_streams': clean}

        try:
            self.api.device(slug).unclaim.post(payload)
        except RestHttpBaseException, exc:
            raise ExternalError("Error calling method on iotile.cloud", exception=exc, response=exc.response.status_code)

    def upload_report(self, report):
        """Upload an IOTile report to the cloud.

        Args:
            report (IOTileReport): The report that you want to upload.  This should
                not be an IndividualReadingReport.

        Returns:
            int: The number of new readings that were accepted by the cloud as novel.
        """

        timestamp = '{}'.format(report.received_time.isoformat())
        payload = {'file': BytesIO(report.encode())}

        resource = self.api.streamer.report

        headers = {}
        authorization_str = '{0} {1}'.format(resource._store['token_type'], resource._store["token"])
        headers['Authorization'] = authorization_str

        resp = requests.post(resource.url(), files=payload, headers=headers, params={'timestamp': timestamp})

        count = resource._process_response(resp)['count']
        return count

    def highest_acknowledged(self, device_id, streamer):
        """Get the highest acknowledged reading for a given streamer

        Args:
            device_id (int): The device whose streamer we are querying
            streamer (int): The streamer on the device that we want info
                about.

        Returns:
            int: The highest reading id that has been acknowledged by the cloud
        """

        slug = self._build_streamer_slug(device_id, streamer)

        try:
            data = self.api.streamer(slug).get()
        except RestHttpBaseException, exc:
            raise ArgumentError("Could not get information for streamer", device_id=device_id, streamer_id=streamer, slug=slug, err=str(exc))

        if 'last_id' not in data:
            raise ExternalError("Response fom the cloud did not have last_id set", response=data)

        return data['last_id']

    @annotated
    def refresh_token(self):
        """Attempt to refresh out cloud token with iotile.cloud
        """
        conf = ConfigManager()
        domain = conf.get('cloud:server')

        url = '{}/api/v1/auth/api-jwt-refresh/'.format(domain)

        resp = requests.post(url, json={'token': self.token})
        if resp.status_code != 200:
            raise ExternalError("Could not refresh token", error_code=resp.status_code)

        data = resp.json()

        # Save token that we just refreshed to the registry and update our own token
        self.token = data['token']
        reg = ComponentRegistry()
        reg.set_config('arch:cloud_token', self.token)
