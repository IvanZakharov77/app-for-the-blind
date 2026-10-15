import unittest

from voiceassist.drives import removable_drive_letters, enumerate_usb_volumes, scan_volumes, bus_type_from_descriptor, volume_arrival_message, UsbVolume, VolumeWatcher


class DriveTests(unittest.TestCase):
    def test_arrival_message_does_not_call_unknown_new_disk_a_flash_drive(self):
        volume = UsbVolume("G", "guid-g", "DATA", "NTFS", False)
        message = volume_arrival_message(volume)
        self.assertEqual(message, "Подключён новый диск G «DATA».")
        self.assertNotIn("подтвержд", message)

    def test_watcher_remembers_startup_volumes_and_reports_only_new_guid(self):
        now = [0.0]
        initial = UsbVolume("E", "guid-one", "Старый", "NTFS", True)
        new = UsbVolume("F", "guid-two", "Новый", "FAT32", True)
        current = [[initial]]
        scans = [0]
        def provider():
            scans[0] += 1
            return tuple(current[0])
        watcher = VolumeWatcher(provider, clock=lambda: now[0], interval=10.0)
        watcher.start()
        current[0] = [initial, new]
        self.assertEqual(watcher.poll(), ())
        self.assertEqual(scans[0], 1)
        now[0] = 10.0
        self.assertEqual(watcher.poll(), (new,))
        self.assertEqual(watcher.poll(), ())

    def test_storage_descriptor_reads_bus_type_at_documented_offset(self):
        payload = bytearray(36)
        payload[4:8] = (36).to_bytes(4, "little")
        payload[28:32] = (7).to_bytes(4, "little")
        self.assertEqual(bus_type_from_descriptor(bytes(payload)), 7)
        with self.assertRaises(ValueError):
            bus_type_from_descriptor(bytes(payload[:20]))

    def test_fixed_usb_volume_is_included_with_stable_identity(self):
        class Api:
            def logical_mask(self): return (1 << 2) | (1 << 4)
            def drive_type(self, root): return 3
            def bus_type(self, letter): return 7 if letter == "E" else 11
            def volume_guid(self, root): return "guid-" + root[0]
            def volume_info(self, root): return ("Фильмы", "FAT32")
        volumes = enumerate_usb_volumes(Api())
        self.assertEqual([(volume.letter, volume.guid, volume.filesystem) for volume in volumes], [("E", "guid-E", "FAT32")])

    def test_startup_scan_includes_non_usb_disks_without_calling_them_usb(self):
        class Api:
            def logical_mask(self): return 1 << 2
            def drive_type(self, root): return 3
            def bus_type(self, letter): return 11
            def volume_guid(self, root): return "guid-C"
            def volume_info(self, root): return ("System", "NTFS")
        volumes = scan_volumes(Api())
        self.assertEqual(len(volumes), 1)
        self.assertFalse(volumes[0].confirmed_usb)

    def test_removable_volume_survives_bus_query_failure(self):
        class Api:
            def logical_mask(self): return 1 << 4
            def drive_type(self, root): return 2
            def bus_type(self, letter): raise OSError("access denied")
            def volume_guid(self, root): return "guid-E"
            def volume_info(self, root): return ("DATA", "exFAT")
        volumes = enumerate_usb_volumes(Api())
        self.assertEqual(len(volumes), 1)
        self.assertFalse(volumes[0].confirmed_usb)

    def test_lists_only_removable_drive_letters(self):
        mask = (1 << 2) | (1 << 4) | (1 << 5)
        kinds = {"C:\\": 3, "E:\\": 2, "F:\\": 2}
        self.assertEqual(removable_drive_letters(lambda: mask, lambda root: kinds[root]), ("E", "F"))

    def test_empty_drive_mask_does_not_claim_a_usb_disk(self):
        self.assertEqual(removable_drive_letters(lambda: 1 << 2, lambda root: 3), ())


if __name__ == "__main__":
    unittest.main()
