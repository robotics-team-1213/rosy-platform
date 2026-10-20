"""Optional production admission stays OFF when absent and refuses bad files."""
import argparse

import pytest

from fleet.server.channel.options import add_conversation_options, load_conversation_options
from test_assistant_provider import configuration


def test_optional_operator_config_is_absent_off_present_strict(tmp_path):
    parser = argparse.ArgumentParser()
    add_conversation_options(parser)
    path = tmp_path/'operator.json'
    args = parser.parse_args(['--assistant-config-optional', str(path)])
    assert load_conversation_options(args)[2] is None
    path.write_text(configuration().model_dump_json())
    assert load_conversation_options(args)[2].execution_enabled is False
    path.write_text('{}')
    with pytest.raises(ValueError): load_conversation_options(args)


def test_required_and_optional_operator_config_cannot_be_mixed():
    parser = argparse.ArgumentParser()
    add_conversation_options(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(['--assistant-config', 'one', '--assistant-config-optional', 'two'])
