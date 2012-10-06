# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

import pkg_resources
from twisted.internet import defer
from twisted.application import strports, service
from twisted.web import server, static, resource
from buildbot import config
from buildbot.www import ui, rest, ws

class WWWService(config.ReconfigurableServiceMixin, service.MultiService):

    def __init__(self, master):
        service.MultiService.__init__(self)
        self.setName('www')
        self.master = master

        self.port = None
        self.port_service = None
        self.site = None

        # load the apps early, in case something goes wrong in Python land
        epAndApps = [ (ep, ep.load())
                for ep in pkg_resources.iter_entry_points('buildbot.www') ]

        # look for duplicate names
        names = set([ ep.name for ep, app in epAndApps ])
        seen = set()
        dupes = set(n for n in names if n in seen or seen.add(n))
        if dupes:
            raise RuntimeError("duplicate buildbot.www entry points: %s"
                                % (dupes,))

        self.apps = dict((ep.name, app) for (ep, app) in epAndApps)

        if 'base' not in self.apps:
            raise RuntimeError("could not find buildbot-www; is it installed?")

    @defer.inlineCallbacks
    def reconfigService(self, new_config):
        www = new_config.www

        need_new_site = False
        if self.site:
            # if config params have changed, set need_new_site to True.
            # There are none right now.
            need_new_site = False
        else:
            if www['port']:
                need_new_site = True

        if need_new_site:
            self.setupSite(new_config)

        if www['port'] != self.port:
            if self.port_service:
                yield defer.maybeDeferred(lambda :
                        self.port_service.disownServiceParent())
                self.port_service = None

            self.port = www['port']
            if self.port:
                port = self.port
                if type(port) is int:
                    port = "tcp:%d" % port
                self.port_service = strports.service(port, self.site)
                self.port_service.setServiceParent(self)

        yield config.ReconfigurableServiceMixin.reconfigService(self,
                                                                new_config)


    def setupSite(self, new_config):
        root = resource.Resource()

        # render the UI HTML at the root
        root.putChild('', ui.UIResource(self.master, self.apps))

        # serve JS from /base and /app/$name
        appComponent = static.Data('app', 'text/plain')
        root.putChild('app', appComponent)
        for name, app in self.apps.iteritems():
            appComponent.putChild(name, static.File(app.static_dir))

        # /api
        root.putChild('api', rest.RestRootResource(self.master))

        # /ws
        root.putChild('ws', ws.WsResource(self.master))

        self.site = server.Site(root)