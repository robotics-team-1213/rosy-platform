"""CLI composition for independently configured conversation surfaces."""
from pathlib import Path


def add_conversation_options(parser):
    parser.add_argument('--conversation-config-optional', default=None, type=Path,
                        help='optional independently admitted natural conversation broker config')
    parser.add_argument('--assistant-config', default=None, type=Path,
                        help='independently admitted read-only Console assistant broker config')
    parser.add_argument('--deliberation-config-optional', default=None, type=Path,
                        help='optional private D-720 fixed read-only status broker config')


def load_conversation_options(args):
    from .model_runtime import BrokerConfig
    from .conversation.runtime import ConversationConfig
    from ..assistant.provider import OperatorConfig
    model = (BrokerConfig.load(args.deliberation_config_optional, optional=True)
             if getattr(args, 'deliberation_config_optional', None) is not None else None)
    conversation = (ConversationConfig.load(args.conversation_config_optional, optional=True)
                    if getattr(args, 'conversation_config_optional', None) is not None else None)
    assistant = (OperatorConfig.load(args.assistant_config)
                 if getattr(args, 'assistant_config', None) is not None else None)
    return model, conversation, assistant
