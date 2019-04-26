import pytest

from koris.util.logger import Logger, LOG_LEVELS, DEFAULT_LOG_LEVEL

# @pytest.fixture(scope="functiion")
# def logger():
#     yield Logger("test")


def test_logger_default_state():
    assert Logger.LOG_LEVEL == DEFAULT_LOG_LEVEL


def test_logger_creation():
    assert Logger.LOG_LEVEL == DEFAULT_LOG_LEVEL

    # OK
    for i in LOG_LEVELS:
        Logger.LOG_LEVEL = i
        log = Logger("test")
        assert log is not None
        assert log.LOG_LEVEL == i


def test_logger_fail():
    # Not OK
    for i in [-1, 100, 23, 42]:
        Logger.LOG_LEVEL = i
        assert Logger.LOG_LEVEL == i

        with pytest.raises(ValueError):
            Logger("test")


# Run tests with -s to verify the output:
# py.test -s tests/test_logger.py
def test_level_logging():
    for i in LOG_LEVELS:
        Logger.LOG_LEVEL = i
        log = Logger(f"test")

        print("----")
        print(f"id(log): {id(log)}")
        print(f"Logger.LOG_LEVEL: {Logger.LOG_LEVEL}")
        print(f"log.LOG_LEVEL: {log.LOG_LEVEL}")
        print(f"log.level: {log.level}")
        print(f"log.handlers: {log.logger.handlers}")
        print("----")

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
