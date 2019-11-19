"""This module defines logging capabilities for koris."""

import logging
import sys
import time

# pylint: disable=no-name-in-module
from koris.util.hue import (bad, red, info as infomsg, yellow, run, grey,
                            que, good, green)

LOG_LEVELS = list(range(5))
DEFAULT_LOG_LEVEL = 3


def get_logger(name):
    """Returns a Python logger.

    Right now, only a single handler which logs to STDOUT can be added to a
    logger. This is because if multiple calls with the same name would add
    duplicate handlers to a logger, which lead to extra prints.

    Args:
        name (str): The name of the Logger.

    Returns:
        A Python Logger.
    """

    log = logging.getLogger(name)
    set_level(log, Logger.LOG_LEVEL)

    # If we instantiate multiple loggers with the same name,
    # we would add duplicate handlers.
    if not log.handlers:
        sh = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("%(message)s")
        sh.setFormatter(fmt)
        log.addHandler(sh)

    return log


def set_level(logger, level):
    """Sets the logging level.

    See `Python Logging Levels
    <https://docs.python.org/3.6/library/logging.html#levels>`_ for
    more information on how the koris levels relate to the original
    Python levels.

    Args:
        logger: A Python logger object.
        level (int): The logging level.

    Raises:
        ValueError if log level is unsupported.
    """

    if level not in LOG_LEVELS:
        raise ValueError(f"log level {level} is not supported")

    logger.disabled = False
    if level == 1:
        logger.setLevel(40)
    elif level == 2:
        logger.setLevel(30)
    elif level == 3:
        logger.setLevel(20)
    elif level == 4:
        logger.setLevel(10)
    else:
        logger.disabled = True


class Singleton(type):
    """Metaclass to implement the Singleton pattern.

    This Metaclass implements the Singleton pattern. This should only be used
    logging purposes to avoid introducing mutable global state into the
    application.

    Metaclasses are classes that instantiate other classes. Everytime a new
    class (any class in Python) is instantiated, it checks what the Metaclass
    of that specific class is, then executes it with certain parameters.

    In our case, the metaclass holds a dictionary that keeps track of all the
    instances that have been created by the Singleton Metaclass. Everytime we
    instantiate or call let's say :class:`koris.util.logger.Logger`, whose
    Metaclass is the Singleton class, we check if we have already have such an
    instance. If yes, that one is returned. If not, we create such an instance,
    add it to the ``_instances`` dict and then return it. Subsequent calls will
    then only return one instance, which is always the same object with the same ID.

    For more information about the pattern, see `Eli's Post
    <https://eli.thegreenplace.net/2011/08/14/python-metaclasses-by-example/>`_
    and `Stack Overflow  <https://stackoverflow.com/a/6798042>`_.

    Example:
        >>> log1 = Logger(__name__)
        >>> log2 = Logger(__name__)
        >>> log1.info("hello")
        [~] hello
        >>> log2.info("world")
        [~] world
        >>> log3 = Logger("koris")
        >>> id(log1) == id(log2) == id(log3)
        True
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        else:
            cls._instances[cls].__init__(*args, **kwargs)

        return cls._instances[cls]


class Logger(metaclass=Singleton):
    """This class provides logging capabilities.

    This class is a singleton that returns as proxy instance of
    logging.Logger.

    Before using, make sure to set Logger.LOG_LEVEL to the desired
    level.

    The different levels are:

    .. code:: shell

        * 0 - quiet (no output)
        * 1 - error
        * 2 - warning
        * 3 - info
        * 4 - debug

    A logger initiated with a specific level will print everything below
    (except 0) but not above.

    All functions except for :meth`.Logger.question` support ``f``-, ``%``-,
    and ``format``-Style formatting.

    Example:
        >>> log = Logger(__name__)
        >>> log.info("hello world")
        [~] hello world
        >>> log.info("%s %s", "hello", "world")
        [~] hello world
        >>> a, b = "hello", "world"
        >>> log.info(f"{a} {b}")
        [~] hello world
        >>> log.info("{} {}".format(b, a))
        [~] world hello

    Attributes:
        LOG_LEVEL (int): The log level to be used across the application.

    Args:
        name (str): The name of the logger.
    """

    LOG_LEVEL = DEFAULT_LOG_LEVEL

    def __init__(self, name):
        self.logger = get_logger(name)

    @property
    def level(self):
        """Returns the Python log level equivalent.

        Returns:
            The Python loglevel equivalent or None if logger not instantiated.
        """
        if not self.logger:
            return None

        if self.logger.disabled:
            return 0

        return self.logger.level

    @level.setter
    def level(self, level):
        level_to_int = {
            'quiet': 0,
            'error': 1,
            'warning': 2,
            'info': 3,
            'debug': 4}

        try:
            level = level_to_int[level]
        except KeyError:
            level = int(level)

        set_level(self.logger, level)

    def error(self, msg, *args, color=True, **kwargs):
        """Logs a message on error level.

        If color is True, will be logged in red with ``[-]``, else
        in plain.

        Example:
            >>> log.error("test")
            [-] test
            >>> log.error("test", color=False)
            test

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        if color:
            msg = bad(red(msg))

        self.logger.error(msg, *args, **kwargs)

    def warning(self, msg, *args, color=True, **kwargs):
        """Logs a message on warning level.

        If color is True, will be logged in yellow with ``[!]``, else
        in plain.

        Example:
            >>> log.warning("test")
            [!] test
            >>> log.warning("test", color=False)
            test

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        if color:
            msg = infomsg(yellow(msg))

        self.logger.warning(msg, *args, **kwargs)

    def warn(self, msg, *args, color=True, **kwargs):
        """Convenience function to log on warning level.

        Will just call :meth:`.Logger.warning`.

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        self.warning(msg, *args, **kwargs, color=color)

    def info(self, msg, *args, color=True, **kwargs):
        """Logs a message on info level.

        If color is True, will be logged in grey with ``[~]``, else
        in plain.

        Example:
            >>> log.info("test")
            [~] test
            >>> log.info("test", color=False)
            test

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        if color:
            msg = run(grey(msg))

        self.logger.info(msg, *args, **kwargs)

    def debug(self, msg, *args, color=True, **kwargs):
        """Logs a message on debug level.

        If color is True, will be logged in grey with the current
        timestamp in brackets as prefix, else in plain.

        Example:
            >>> log.debug("test")
            [20190426-155611] test
            >>> log.debug("test", color=False)
            test

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored.
        """

        if color:
            now = time.strftime("%Y%m%d-%H%M%S")
            msg = grey(f"[{now}] {msg}")

        self.logger.debug(msg, *args, **kwargs)

    def success(self, msg, *args, color=True, **kwargs):
        """Indicates a success.

        Messages are printend on info level.

        If color is True, will be logged in green with ``[+]``, else
        in plain.

        Example:
            >>> log.info("test")
            [~] test
            >>> log.success("test")
            [+] test
            >>> log.success("test", color=False)
            test

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

        If color is True, will be logged in green with ``[+]``, else
        in plain.

        Example:
            >>> log.question("test")
            [?] test
            >>> log.question("test", color=False)
            test

        Args:
            msg (str): The message to be logged.
            color (bool): If the message should be colored
        """

        if color:
            msg = que(msg)

        print(msg)
