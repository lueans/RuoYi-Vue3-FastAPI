"""Closed public completion contract shared by local Agent drivers."""

import re


def completion_schema(offer):
    if offer.intent == 'discuss':
        properties = {
            'completionState': {'type': 'string', 'enum': ['message_completed']},
            'title': {'type': ['string', 'null'], 'maxLength': 200},
            'content': {'type': 'string', 'minLength': 1, 'maxLength': 20_000},
            'contentType': {'type': 'string', 'enum': ['text/plain']},
        }
    else:
        properties = {
            'completionState': {'type': 'string', 'enum': [
                'direct_completed' if offer.execution_mode == 'direct' else 'artifact_completed', 'needs_input',
            ]},
            'title': {'type': ['string', 'null'], 'maxLength': 200},
            'questions': {'type': 'array', 'maxItems': 3, 'items': {
                'type': 'object', 'properties': {
                    'questionId': {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_-]{0,31}$'},
                    'prompt': {'type': 'string', 'minLength': 1, 'maxLength': 300},
                }, 'required': ['questionId', 'prompt'], 'additionalProperties': False,
            }},
        }
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def validate_completion(value, offer):
    # Don't transmit unexpected provider output and rely on the server to
    # reject it later; enforce the closed public contract on the device too.
    schema = completion_schema(offer)
    if not isinstance(value, dict) or set(value) != set(schema['required']):
        raise ValueError('Completion fields invalid')
    if value['completionState'] not in schema['properties']['completionState']['enum']:
        raise ValueError('Completion state invalid')
    if value['title'] is not None and (not isinstance(value['title'], str) or len(value['title']) > 200):
        raise ValueError('Completion title invalid')
    if offer.intent == 'discuss':
        if (not isinstance(value['content'], str) or not 1 <= len(value['content']) <= 20_000
                or value['contentType'] != 'text/plain'):
            raise ValueError('Message content invalid')
    else:
        questions = value['questions']
        if not isinstance(questions, list) or len(questions) > 3:
            raise ValueError('Questions invalid')
        needs_input = value['completionState'] == 'needs_input'
        if needs_input != bool(questions) or (needs_input and value['title'] not in (None, '')):
            raise ValueError('Questions inconsistent with completion')
        ids = set()
        for question in questions:
            if (not isinstance(question, dict) or set(question) != {'questionId', 'prompt'}
                    or not isinstance(question['questionId'], str)
                    or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', question['questionId'])
                    or question['questionId'] in ids or not isinstance(question['prompt'], str)
                    or not 1 <= len(question['prompt']) <= 300):
                raise ValueError('Question invalid')
            ids.add(question['questionId'])
    return value
