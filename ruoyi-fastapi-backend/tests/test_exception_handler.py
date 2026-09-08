from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.constant import HttpStatusConstant
from exceptions.exception import INTERNAL_SERVER_ERROR_MESSAGE
from exceptions.handle import handle_exception


def test_unhandled_exception_does_not_expose_internal_details() -> None:
    app = FastAPI()

    @app.get('/explode')
    async def explode() -> None:
        raise RuntimeError('SELECT secret_column FROM private_table')

    handle_exception(app)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/explode')

    payload = response.json()
    assert payload['code'] == HttpStatusConstant.ERROR
    assert payload['msg'] == INTERNAL_SERVER_ERROR_MESSAGE
    assert 'secret_column' not in response.text
    assert 'private_table' not in response.text
