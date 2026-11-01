"""Compatibility adapter; all novel configuration policy belongs to the plugin."""
from .novel_plugin import console_service


def parse_configuration(text: str, mode: str):
    return console_service().configuration.parse_configuration(text, mode)


def parse_advisor(text: str, mode: str):
    return console_service().configuration.parse_advisor(text, mode)
