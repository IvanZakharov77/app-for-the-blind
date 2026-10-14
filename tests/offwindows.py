"""Keeps Assistant from reaching real Windows parts (windows, burners, drives) while tests run on Windows."""
import sys
import types
from unittest import mock


class _NotWindows(types.ModuleType):
    platform = "linux"

    def __getattr__(self, name):
        return getattr(sys, name)


_patch = mock.patch("voiceassist.core.sys", _NotWindows("sys"))


def setUpModule():
    _patch.start()


def tearDownModule():
    _patch.stop()
