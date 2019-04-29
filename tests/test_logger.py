import pytest

from koris.util.logger import Logger, LOG_LEVELS


def test_logger_creation():
    # OK
    for i in LOG_LEVELS:
        assert Logger(i)
        assert Logger(i, "test")

    # Not OK
    for i in [-1, 100, 23, 42]:
        with pytest.raises(ValueError):
            Logger(i)


def test_set_level():
    log = Logger(1)

    # OK
    for i in LOG_LEVELS:
        log.set_level(i)

    # # Not OK
    for i in [-1, 100, 23, 42]:
        with pytest.raises(ValueError):
            log.set_level(i)


def test_level_logging():
    for i in LOG_LEVELS:
        print(f"-- Logging on level {i} --")
        log = Logger(i)
        msg = "The quick brown fox jumps over the lazy dog"
        msg2 = "-123.00"

        log.error("Logging errors")
        log.error(msg)
        log.error(msg, color=False)
        log.error("%s: %s", msg, msg2)
        log.error("%s: %s", msg, msg2, color=False)

        log.warning("Logging warnings #1")
        log.warning(msg)
        log.warning(msg, color=False)
        log.warning("%s: %s", msg, msg2)
        log.warning("%s: %s", msg, msg2, color=False)

        log.warning("Logging warnings #2")
        log.warn(msg)
        log.warn(msg, color=False)
        log.warn("%s: %s", msg, msg2)
        log.warn("%s: %s", msg, msg2, color=False)

        log.info("Logging infos")
        log.info(msg)
        log.info(msg, color=False)
        log.info("%s: %s", msg, msg2)
        log.info("%s: %s", msg, msg2, color=False)

        log.debug("Logging debugs")
        log.debug(msg)
        log.debug(msg, color=False)
        log.debug("%s: %s", msg, msg2)
        log.debug("%s: %s", msg, msg2, color=False)

        log.question("Logging questions")
        log.question(msg)
        log.question(msg, color=False)

        log.success("Logging successes")
        log.success(msg)
        log.success(msg, color=False)
        log.success("%s: %s", msg, msg2)
        log.success("%s: %s", msg, msg2, color=False)
        print()