import re
import unittest

from autoflash.interaction import uboot


class FakeReader:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.writes = []
        self.asserted_prompts = []

    def write(self, data):
        self.writes.append(data)

    def wait_for_prompt_match(self, prompt_regex):
        response = next(self.responses)
        self.asserted_prompts.append(prompt_regex)
        match = re.search(prompt_regex, response)
        if not match:
            raise AssertionError(f"{prompt_regex!r} did not match {response!r}")
        return match.group(0)

    def log_buffer_as_error(self):
        pass


class EnsureReadyTest(unittest.TestCase):
    def test_tries_passwords_until_one_succeeds(self):
        reader = FakeReader(
            [
                "Password for uboot cmd line :",
                "Password for uboot cmd line :",
                "ar7240>",
            ]
        )

        matched = uboot.ensure_ready(reader, ["wrong", "correct"], "new-secret")

        self.assertEqual(matched, "correct")
        self.assertEqual(reader.writes, [b"\n", b"wrong\n", b"correct\n"])

    def test_sets_new_password_when_none_exists(self):
        reader = FakeReader(["New password:", "Confirm  password:", "ar7240>"])

        matched = uboot.ensure_ready(reader, ["old"], "new-secret")

        self.assertIsNone(matched)
        self.assertEqual(reader.writes, [b"\n", b"new-secret\n", b"new-secret\n"])

    def test_fails_after_all_passwords_are_rejected(self):
        reader = FakeReader(
            [
                "Password for uboot cmd line :",
                "Password for uboot cmd line :",
                "Password for uboot cmd line :",
                "Password is wrong, System will reboot...",
            ]
        )

        with self.assertRaises(uboot.WrongBootloaderPasswordError):
            uboot.ensure_ready(reader, ["one", "two", "three"], "new-secret")

        self.assertEqual(reader.writes, [b"\n", b"one\n", b"two\n", b"three\n"])


class ChangePasswordTest(unittest.TestCase):
    def test_changes_password(self):
        reader = FakeReader(
            [
                "Confirm old password :",
                "Please enter new password :",
                "Please confirm new password :",
                "The password is changed successfully.\nar7240>",
            ]
        )
        uboot.change_password(reader, "old-secret", "new-secret")

        self.assertEqual(
            reader.writes,
            [b"passwd\n", b"old-secret\n", b"new-secret\n", b"new-secret\n"],
        )
        self.assertEqual(
            reader.asserted_prompts,
            [
                uboot.PROMPT_CONFIRM_OLD_PASSWORD,
                uboot.PROMPT_ENTER_NEW_PASSWORD,
                uboot.PROMPT_CONFIRM_NEW_PASSWORD,
                rf"{uboot.PASSWORD_CHANGED}\s*{uboot.PROMPT_UBOOT_READY}",
            ],
        )


if __name__ == "__main__":
    unittest.main()
