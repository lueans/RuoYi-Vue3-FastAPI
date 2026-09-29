<template>
  <div class="app-container">
    <el-alert
      v-if="hasModelFilter || fromMindmap"
      class="modelRecoveryBanner"
      :title="invalidModelFilter ? '模型定位链接无效' : repairModelId ? `正在定位模型 #${repairModelId}` : '从 AI 脑图打开的模型管理'"
      :type="invalidModelFilter ? 'warning' : 'info'"
      :closable="false"
      show-icon
      role="status"
    >
      <span v-if="invalidModelFilter" class="modelRecoveryLine">链接中的模型编号无效，未查询其他模型。请返回原对话重新打开，或查看全部模型。</span>
      <span v-else-if="repairModelId" class="modelRecoveryLine">当前列表仅显示此模型，操作仍受当前账号权限限制。</span>
      <span v-if="fromMindmap" class="modelRecoveryLine">脑图对话仍在原标签页。保存配置后返回对话，点击“重新检查配置”；不会自动切换模型或发送任务。</span>
      <el-button v-if="hasModelFilter" text type="primary" @click="clearModelFilter">查看全部模型</el-button>
    </el-alert>
    <el-alert v-if="listError" :title="listError" type="error" :closable="false" show-icon class="modelRecoveryBanner" role="status">
      <el-button text type="primary" :loading="loading" @click="getList">重新加载模型</el-button>
    </el-alert>
    <el-form
      :model="queryParams"
      ref="queryRef"
      :inline="true"
      v-show="showSearch"
    >
      <el-form-item label="模型编码" prop="modelCode">
        <el-input
          v-model="queryParams.modelCode"
          placeholder="请输入模型编码"
          clearable
          style="width: 200px"
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="提供商" prop="provider">
        <el-select
          v-model="queryParams.provider"
          placeholder="请选择提供商"
          clearable
          style="width: 200px"
          @keyup.enter="handleQuery"
        >
          <el-option
            v-for="dict in ai_provider_type"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-select
          v-model="queryParams.status"
          placeholder="模型状态"
          clearable
          style="width: 240px"
        >
          <el-option
            v-for="dict in sys_normal_disable"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="handleQuery"
          >搜索</el-button
        >
        <el-button icon="Refresh" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button
          type="primary"
          plain
          icon="Plus"
          @click="handleAdd"
          v-hasPermi="['ai:model:add']"
          >新增</el-button
        >
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="success"
          plain
          icon="Edit"
          :disabled="single"
          @click="handleUpdate"
          v-hasPermi="['ai:model:edit']"
          >修改</el-button
        >
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="danger"
          plain
          icon="Delete"
          :disabled="multiple"
          @click="handleDelete"
          v-hasPermi="['ai:model:remove']"
          >删除</el-button
        >
      </el-col>
      <right-toolbar
        v-model:showSearch="showSearch"
        @queryTable="getList"
      ></right-toolbar>
    </el-row>

    <el-table
      v-loading="loading"
      :data="modelList"
      :empty-text="invalidModelFilter ? '模型编号无效，请重新选择' : listError ? '模型列表未加载，请重试' : repairModelId ? '未找到该模型或没有查看权限，也可清除其他筛选后重试' : '暂无模型'"
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="55" align="center" />
      <el-table-column label="模型ID" align="center" prop="modelId" />
      <el-table-column label="模型编码" align="center" prop="modelCode" />
      <el-table-column label="提供商" align="center" prop="provider">
        <template #default="scope">
          <dict-tag :options="ai_provider_type" :value="scope.row.provider" />
        </template>
      </el-table-column>
      <el-table-column label="支持推理" align="center" prop="supportReasoning">
        <template #default="scope">
          <dict-tag :options="sys_yes_no" :value="scope.row.supportReasoning" />
        </template>
      </el-table-column>
      <el-table-column label="支持图片" align="center" prop="supportImages">
        <template #default="scope">
          <dict-tag :options="sys_yes_no" :value="scope.row.supportImages" />
        </template>
      </el-table-column>
      <el-table-column label="状态" align="center" prop="status">
        <template #default="scope">
          <dict-tag :options="sys_normal_disable" :value="scope.row.status" />
        </template>
      </el-table-column>
      <el-table-column
        label="创建时间"
        align="center"
        prop="createTime"
        width="180"
      >
        <template #default="scope">
          <span>{{ parseTime(scope.row.createTime) }}</span>
        </template>
      </el-table-column>
      <el-table-column
        label="操作"
        width="180"
        align="center"
        class-name="small-padding fixed-width"
      >
        <template #default="scope">
          <el-button
            link
            type="primary"
            icon="Edit"
            @click="handleUpdate(scope.row)"
            v-hasPermi="['ai:model:edit']"
            >修改</el-button
          >
          <el-button
            link
            type="primary"
            icon="Delete"
            @click="handleDelete(scope.row)"
            v-hasPermi="['ai:model:remove']"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <pagination
      v-show="total > 0"
      :total="total"
      v-model:page="queryParams.pageNum"
      v-model:limit="queryParams.pageSize"
      @pagination="getList"
    />

    <!-- 添加或修改对话框 -->
    <el-dialog :title="title" v-model="open" width="700px" append-to-body>
      <el-form ref="modelRef" :model="form" :rules="rules" label-width="100px">
        <el-row :gutter="10">
          <el-col :span="12">
            <el-form-item label="模型编码" prop="modelCode">
              <el-input
                v-model="form.modelCode"
                placeholder="请输入模型编码 (如 deepseek-r1)"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="模型名称" prop="modelName">
              <el-input v-model="form.modelName" placeholder="请输入模型名称" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="提供商" prop="provider">
              <el-select
                v-model="form.provider"
                placeholder="请选择提供商"
                style="width: 100%"
              >
                <el-option
                  v-for="dict in ai_provider_type"
                  :key="dict.value"
                  :label="dict.label"
                  :value="dict.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="模型排序" prop="modelSort">
              <el-input-number
                v-model="form.modelSort"
                :min="0"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="API Key" prop="apiKey">
              <el-input
                v-model="form.apiKey"
                placeholder="请输入API Key"
                type="password"
              />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="Base URL" prop="baseUrl">
              <el-input v-model="form.baseUrl" placeholder="请输入Base URL" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="最大输出" prop="maxTokens">
              <el-input-number
                v-model="form.maxTokens"
                :min="0"
                style="width: 100%"
                placeholder="最大输出"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="默认温度" prop="temperature">
              <el-input-number
                v-model="form.temperature"
                :min="0"
                :max="2"
                :step="0.1"
                placeholder="默认温度"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="支持推理" prop="supportReasoning">
              <el-radio-group v-model="form.supportReasoning">
                <el-radio
                  v-for="dict in sys_yes_no"
                  :key="dict.value"
                  :value="dict.value"
                  >{{ dict.label }}</el-radio
                >
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="支持图片" prop="supportImages">
              <el-radio-group v-model="form.supportImages">
                <el-radio
                  v-for="dict in sys_yes_no"
                  :key="dict.value"
                  :value="dict.value"
                  >{{ dict.label }}</el-radio
                >
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="模型类型" prop="modelType">
              <el-input
                v-model="form.modelType"
                placeholder="请输入模型类型 (可选)"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态" prop="status">
              <el-radio-group v-model="form.status">
                <el-radio
                  v-for="dict in sys_normal_disable"
                  :key="dict.value"
                  :value="dict.value"
                  >{{ dict.label }}</el-radio
                >
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注" prop="remark">
              <el-input
                v-model="form.remark"
                type="textarea"
                placeholder="请输入内容"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button type="primary" @click="submitForm">确 定</el-button>
          <el-button @click="cancel">取 消</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="AiModel">
import { computed, getCurrentInstance, onBeforeUnmount, reactive, ref, toRefs, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import useUserStore from '@/store/modules/user';
import { normalizeModelRecoveryId } from '@/utils/mindmap-model-recovery';
import {
  listModel,
  addModel,
  delModel,
  getModel,
  updateModel,
} from "@/api/ai/model";

const { proxy } = getCurrentInstance();
const route = useRoute();
const router = useRouter();
// The admin menu may mount this component at a customized path. Bind requests
// to this page instance, not to the default menu URL.
const modelPagePath = route.path;
const userStore = useUserStore();
const hasModelFilter = computed(() => route.query.modelId !== undefined);
const repairModelId = computed(() => normalizeModelRecoveryId(route.query.modelId));
const invalidModelFilter = computed(() => hasModelFilter.value && repairModelId.value === null);
const fromMindmap = computed(() => route.query.from === 'mindmap-agent');
const { ai_provider_type, sys_normal_disable, sys_yes_no } = proxy.useDict(
  "ai_provider_type",
  "sys_normal_disable",
  "sys_yes_no",
);

const modelList = ref([]);
const open = ref(false);
const loading = ref(true);
const showSearch = ref(true);
const ids = ref([]);
const single = ref(true);
const multiple = ref(true);
const total = ref(0);
const title = ref("");
const listError = ref("");
let listGeneration = 0;
let listController = null;
let modelPageAlive = true;

const data = reactive({
  form: {},
  queryParams: {
    pageNum: 1,
    pageSize: 10,
    modelId: undefined,
    modelCode: undefined,
    provider: undefined,
    status: undefined,
  },
  rules: {
    modelCode: [
      { required: true, message: "模型编码不能为空", trigger: "blur" },
    ],
    provider: [
      { required: true, message: "提供商不能为空", trigger: "change" },
    ],
    modelSort: [
      { required: true, message: "模型排序不能为空", trigger: "blur" },
    ],
  },
});

const { queryParams, form, rules } = toRefs(data);

/** 查询列表 */
function invalidateModelList() {
  listGeneration++;
  listController?.abort();
  listController = null;
  loading.value = false;
}

async function getList() {
  invalidateModelList();
  modelList.value = [];
  total.value = 0;
  handleSelectionChange([]);
  listError.value = "";
  if (!modelPageAlive || route.path !== modelPagePath || !userStore.id || invalidModelFilter.value) return false;
  const generation = listGeneration;
  const owner = userStore.id;
  const targetId = repairModelId.value;
  const controller = new AbortController();
  listController = controller;
  const current = () => modelPageAlive && listGeneration === generation
    && userStore.id === owner && route.path === modelPagePath
    && repairModelId.value === targetId && !invalidModelFilter.value;
  loading.value = true;
  try {
    // Freeze the submitted filters: typing or following another repair link
    // must not relabel an in-flight response as a different model's results.
    const response = await listModel({ ...queryParams.value, modelId: targetId ?? undefined }, {
      signal: controller.signal, silentError: true,
    });
    if (!current()) return false;
    if (!Array.isArray(response?.rows) || !Number.isSafeInteger(response.total) || response.total < 0) {
      throw new Error('Invalid model list');
    }
    modelList.value = response.rows;
    total.value = response.total;
    return true;
  } catch {
    if (current() && !controller.signal.aborted) listError.value = '模型列表加载失败，请检查连接或权限后重试。';
    return false;
  } finally {
    if (generation === listGeneration) {
      loading.value = false;
      if (listController === controller) listController = null;
    }
  }
}

async function clearModelFilter() {
  const query = { ...route.query };
  delete query.modelId;
  try {
    await router.replace({ path: modelPagePath, query });
  } catch {
    listError.value = '无法清除模型定位，请重试。';
  }
}

/** 取消按钮 */
function cancel() {
  open.value = false;
  reset();
}

/** 表单重置 */
function reset() {
  form.value = {
    modelId: undefined,
    modelCode: undefined,
    modelName: undefined,
    provider: undefined,
    modelSort: 0,
    apiKey: undefined,
    baseUrl: undefined,
    maxTokens: undefined,
    temperature: undefined,
    supportReasoning: "N",
    supportImages: "N",
    modelType: undefined,
    status: "0",
    remark: undefined,
  };
  proxy.resetForm("modelRef");
}

/** 搜索按钮操作 */
function handleQuery() {
  queryParams.value.pageNum = 1;
  getList();
}

/** 重置按钮操作 */
function resetQuery() {
  proxy.resetForm("queryRef");
  handleQuery();
}

/** 多选框选中数据 */
function handleSelectionChange(selection) {
  ids.value = selection.map((item) => item.modelId);
  single.value = selection.length != 1;
  multiple.value = !selection.length;
}

/** 新增按钮操作 */
function handleAdd() {
  reset();
  open.value = true;
  title.value = "添加模型";
}

/** 修改按钮操作 */
function handleUpdate(row) {
  reset();
  const modelId = row.modelId || ids.value;
  getModel(modelId).then((response) => {
    form.value = response.data;
    open.value = true;
    title.value = "修改模型";
  });
}

/** 提交按钮 */
function submitForm() {
  proxy.$refs["modelRef"].validate((valid) => {
    if (valid) {
      if (form.value.modelId != undefined) {
        updateModel(form.value).then((response) => {
          proxy.$modal.msgSuccess("修改成功");
          open.value = false;
          getList();
        });
      } else {
        addModel(form.value).then((response) => {
          proxy.$modal.msgSuccess("新增成功");
          open.value = false;
          getList();
        });
      }
    }
  });
}

/** 删除按钮操作 */
function handleDelete(row) {
  const modelIds = row.modelId || ids.value;
  proxy.$modal
    .confirm('是否确认删除模型编号为"' + modelIds + '"的数据项？')
    .then(function () {
      return delModel(modelIds);
    })
    .then(() => {
      getList();
      proxy.$modal.msgSuccess("删除成功");
    })
    .catch(() => {});
}

watch([() => route.path, () => route.query.modelId, () => userStore.id], () => {
  invalidateModelList();
  modelList.value = [];
  total.value = 0;
  handleSelectionChange([]);
  listError.value = '';
  if (!modelPageAlive || route.path !== modelPagePath || !userStore.id) return;
  // A new repair target must not inherit unrelated search filters, including
  // when this page is reused from the application's keep-alive cache.
  Object.assign(queryParams.value, { pageNum: 1, modelId: repairModelId.value ?? undefined,
    modelCode: undefined, provider: undefined, status: undefined });
  void getList();
}, { immediate: true });
onBeforeUnmount(() => { modelPageAlive = false; invalidateModelList(); });
</script>

<style scoped>
.modelRecoveryBanner { margin-bottom: 16px; }
.modelRecoveryLine { display: block; margin: 6px 0; overflow-wrap: anywhere; }
</style>
