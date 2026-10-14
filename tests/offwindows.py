"""Keeps Assistant from reaching real Windows parts (windows, burners, drives) and the internet while tests run."""
import sys
import types
from unittest import mock


class _NotWindows(types.ModuleType):
    platform = "linux"

    def __getattr__(self, name):
        return getattr(sys, name)


def _offline(url):
    from voiceassist.online import Offline
    raise Offline("tests do not use the network")


def _offline_info(*args, **kwargs):
    from voiceassist.online import OnlineInfo
    return OnlineInfo(*args, **kwargs) if args or kwargs else OnlineInfo(_offline)


_patches = (mock.patch("voiceassist.core.sys", _NotWindows("sys")), mock.patch("voiceassist.file_browser.sys", _NotWindows("sys")),
            mock.patch("voiceassist.core.OnlineInfo", _offline_info))


def setUpModule():
    for patch in _patches:
        patch.start()


def tearDownModule():
    for patch in _patches:
        patch.stop()
