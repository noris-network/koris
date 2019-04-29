"""This module defines logging capabilities for koris."""

import logging
import sys
import time
import builtins

# pylint: disable=no-name-in-module
from koris.util.hue import (bad, red, info, yellow, run, grey, debug,
                            que, blue, good, green)

LOGGER_NAME = 'koris-root-log'
FMT = logging.Formatter("%(message)s")
DEFAULT_HANDLER = logging.StreamHandler(sys.stdout)
LOG_LEVELS = [x for x in range(5)]


class Logger():
    """This class provides logging capabilities.

    This class is more or less a wrapper around Python's own Logging library,
    with additional koris-specific settings being set.

    The different levels are:
    * 0 - quiet (no output)
    * 1 - error
    * 2 - warning
    * 3 - info
    * 4 - debug

    A logger initiated with a specific level will print everything below
    (except 0) but not above.

    Args:
        level (int): The logging level.
    """

    def __init__(self, level=None, name=LOGGER_NAME):
        self.logger = logging.getLogger(name)

        if level is None:
            level = builtins.LOG_LEVEL
        else:
            self.set_level(level)

        DEFAULT_HANDLER.setFormatter(FMT)
        self.logger.addHandler(DEFAULT_HANDLER)

    def set_level(self, level):
        """Sets the logging level.

        See `Python Logging Levels
        <https://docs.python.org/3.6/library/logging.html#levels>`_ for
        more information on how the koris levels relate to the original
        Python levels.

        Args:
            logger: A Pythion logger object.
            level (int): The logging level.

        Raises:
            ValueError if log level is unsupported.
        """

        if level not in LOG_LEVELS:
            raise ValueError(f"log level {level} is not supported")

        self.logger.disabled = False
        if level == 1:
            self.logger.setLevel(40)
        elif level == 2:
            self.logger.setLevel(30)
        elif level == 3:
            self.logger.setLevel(20)
        elif level == 4:
            self.logger.setLevel(10)
        else:
            self.logger.disabled = True

    def error(self, msg, *args, color=True, **kwargs):
        """Logs a message on error level.

        If color is True, will be logged in red with an
        exclamation mark.

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        if color:
            msg = bad(red(msg))

        self.logger.error(msg, *args, **kwargs)

    def warning(self, msg, *args, color=True, **kwargs):
        """Logs a message on warning level.

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        if color:
            msg = info(yellow(msg))

        self.logger.warning(msg, *args, **kwargs)

    def warn(self, msg, *args, color=True, **kwargs):
        """Convenience function to log on warning level.

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        self.warning(msg, *args, **kwargs, color=color)

    def info(self, msg, *args, color=True, **kwargs):
        """Logs a message on info level.

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        if color:
            msg = run(grey(msg))

        self.logger.warning(msg, *args, **kwargs)

    def debug(self, msg, *args, color=True, **kwargs):
        """Logs a message on debug level.

        On debug, we will include a timestamp too if color is set tu
        True.

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        if color:
            now = time.strftime("%Y%m%d-%H%M%S")
            msg = debug(grey(f"{now} {msg}"))

        self.logger.debug(msg, *args, **kwargs)

    def success(self, msg, *args, color=True, **kwargs):
        """Indicates a success.

        Successes are printed on info level by default.

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored
        """

        if color:
            msg = good(green(msg))

        self.logger.info(msg, *args, **kwargs)

    @staticmethod
    def question(msg, color=True):
        """Outputs a question.

        Questions are unaffected by the log level and always printed.

        This function does not support the %-formatting syntax.

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored
        """

        if color:
            msg = que(blue(msg))

        print(msg)
