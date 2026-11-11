import logging

from trailcam.logging import MASK, SecretMaskingFilter, setup_logging


def test_filter_masks_known_secret():
    f = SecretMaskingFilter(["s3cr3t-pass", "deadbeef" * 4])
    assert f.mask("login with s3cr3t-pass now") == f"login with {MASK} now"
    assert "deadbeef" not in f.mask("key=" + "deadbeef" * 4)


def test_filter_masks_json_password():
    f = SecretMaskingFilter()
    out = f.mask('{"cmdId":0,"usrName":"admin","password":"hunter2","x":1}')
    assert "hunter2" not in out
    assert '"password":"***"' in out
    assert '"usrName":"admin"' in out


def test_filter_masks_kv_forms():
    f = SecretMaskingFilter()
    assert "topsecret" not in f.mask("CAM_PASSWORD=topsecret")
    assert "topsecret" not in f.mask("CAM_AES_KEY: topsecret")


def test_logging_pipeline_masks(caplog):
    f = setup_logging("DEBUG", ["my-password-123"])
    log = logging.getLogger("test.mask")
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            f.filter(record)
            records.append(record.getMessage())

    log.addHandler(Capture())
    log.info("password is %s", "my-password-123")
    log.debug('sent {"password":"my-password-123"}')
    joined = "\n".join(records)
    assert "my-password-123" not in joined
    assert MASK in joined
