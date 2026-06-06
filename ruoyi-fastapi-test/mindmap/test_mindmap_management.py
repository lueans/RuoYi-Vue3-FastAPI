"""脑图管理模块集成测试"""
import pytest
import requests
from common.config import Config
from common.login_helper import LoginHelper


BASE_URL = f'{Config.backend_url}/mindmap'


@pytest.fixture(scope='class')
def admin_headers():
    """获取管理员认证 headers"""
    helper = LoginHelper()
    token = helper.login()
    assert token is not None, '登录失败'
    return {'Authorization': f'Bearer {token}'}


class TestMindmapManagement:
    """脑图管理测试"""

    created_ids = []

    def teardown_class(self):
        """清理所有测试创建的脑图"""
        if self.created_ids:
            helper = LoginHelper()
            token = helper.login()
            headers = {'Authorization': f'Bearer {token}'}
            for mid in self.created_ids:
                requests.delete(f'{BASE_URL}/{mid}', headers=headers)

    def test_01_add_mindmap(self, admin_headers):
        """测试新增脑图"""
        data = {
            'name': '测试脑图',
            'nodeTree': {'data': {'text': '根节点'}, 'children': []},
            'layout': 'logicalStructure'
        }
        res = requests.post(BASE_URL, json=data, headers=admin_headers)
        assert res.json()['code'] == 200

    def test_02_list_mindmap(self, admin_headers):
        """测试查询脑图列表"""
        res = requests.get(f'{BASE_URL}/list', params={'pageNum': 1, 'pageSize': 10}, headers=admin_headers)
        assert res.json()['code'] == 200
        assert 'rows' in res.json()

    def test_03_crud_lifecycle(self, admin_headers):
        """测试完整 CRUD 生命周期"""
        # 1. 新增
        data = {
            'name': 'CRUD测试脑图',
            'nodeTree': {'data': {'text': '中心'}, 'children': []},
        }
        res = requests.post(BASE_URL, json=data, headers=admin_headers)
        assert res.json()['code'] == 200

        # 2. 列表查找
        res = requests.get(f'{BASE_URL}/list', params={'name': 'CRUD测试脑图'}, headers=admin_headers)
        rows = res.json()['rows']
        assert len(rows) > 0
        mindmap_id = rows[0]['id']
        self.created_ids.append(mindmap_id)

        # 3. 详情
        res = requests.get(f'{BASE_URL}/{mindmap_id}', headers=admin_headers)
        assert res.json()['code'] == 200
        assert res.json()['data']['name'] == 'CRUD测试脑图'

        # 4. 重命名
        res = requests.put(f'{BASE_URL}/rename', json={'id': mindmap_id, 'name': '已重命名'}, headers=admin_headers)
        assert res.json()['code'] == 200

        # 5. 更新内容
        res = requests.put(f'{BASE_URL}/content', json={
            'id': mindmap_id,
            'nodeTree': {'data': {'text': '更新后'}, 'children': [{'data': {'text': '新子节点'}}]}
        }, headers=admin_headers)
        assert res.json()['code'] == 200

        # 6. 复制
        res = requests.post(f'{BASE_URL}/copy/{mindmap_id}', headers=admin_headers)
        assert res.json()['code'] == 200

        # 7. 删除
        res = requests.delete(f'{BASE_URL}/{mindmap_id}', headers=admin_headers)
        assert res.json()['code'] == 200
        self.created_ids.clear()

    def test_04_nonexistent_mindmap(self, admin_headers):
        """测试访问不存在的脑图"""
        res = requests.get(f'{BASE_URL}/999999999', headers=admin_headers)
        assert res.json()['code'] != 200

    def test_05_duplicate_name(self, admin_headers):
        """测试同用户下名称唯一性"""
        import uuid
        unique_name = f'唯一性测试_{uuid.uuid4().hex[:8]}'
        data = {
            'name': unique_name,
            'nodeTree': {'data': {'text': '中心'}, 'children': []},
        }
        # 第一次创建应成功
        res1 = requests.post(BASE_URL, json=data, headers=admin_headers)
        assert res1.json()['code'] == 200

        # 第二次同名创建应失败
        res2 = requests.post(BASE_URL, json=data, headers=admin_headers)
        assert res2.json()['code'] != 200

        # 清理：删除创建的脑图
        res = requests.get(f'{BASE_URL}/list', params={'name': unique_name}, headers=admin_headers)
        for row in res.json().get('rows', []):
            requests.delete(f'{BASE_URL}/{row["id"]}', headers=admin_headers)
