<template>
  <div class="app-container">
    <el-form :model="queryParams" ref="queryRef" :inline="true" v-show="showSearch" label-width="68px">
      <el-form-item label="文件名" prop="fileName">
        <el-input
          v-model="queryParams.fileName"
          placeholder="请输入文件名"
          clearable
          style="width: 240px"
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="文件后缀" prop="fileSuffix">
        <el-input
          v-model="queryParams.fileSuffix"
          placeholder="请输入文件后缀"
          clearable
          style="width: 240px"
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="创建时间" style="width: 308px">
        <el-date-picker
          v-model="dateRange"
          value-format="YYYY-MM-DD HH:mm:ss"
          type="daterange"
          range-separator="-"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
        ></el-date-picker>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="handleQuery">搜索</el-button>
        <el-button icon="Refresh" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button
          type="primary"
          plain
          icon="Upload"
          @click="handleAdd"
          v-hasPermi="['system:file:upload']"
        >上传文件</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="danger"
          plain
          icon="Delete"
          :disabled="multiple"
          @click="handleDelete"
          v-hasPermi="['system:file:remove']"
        >删除</el-button>
      </el-col>
      <right-toolbar v-model:showSearch="showSearch" @queryTable="getList"></right-toolbar>
    </el-row>

    <el-table v-loading="loading" :data="fileList" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="55" align="center" />
      <el-table-column label="文件ID" align="center" prop="fileId" />
      <el-table-column label="文件名" align="center" prop="fileName" :show-overflow-tooltip="true" />
      <el-table-column label="后缀" align="center" prop="fileSuffix" />
      <el-table-column label="大小" align="center" prop="fileSize">
        <template #default="scope">
          <span>{{ formatFileSize(scope.row.fileSize) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="预览" align="center" prop="filePath">
         <template #default="scope">
            <el-image
              v-if="isImage(scope.row.fileSuffix)"
              style="width: 50px; height: 50px"
              :src="scope.row.filePath"
              :preview-src-list="[scope.row.filePath]"
              fit="contain"
            />
            <span v-else>无法预览</span>
         </template>
      </el-table-column>
      <el-table-column label="创建者" align="center" prop="updateBy" />
      <el-table-column label="创建时间" align="center" prop="createTime" width="180">
        <template #default="scope">
          <span>{{ parseTime(scope.row.createTime) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" align="center" class-name="small-padding fixed-width">
        <template #default="scope">
          <el-button
            link
            type="primary"
            icon="Download"
            @click="handleDownload(scope.row)"
          >下载</el-button>
          <el-button
            link
            type="primary"
            icon="Delete"
            @click="handleDelete(scope.row)"
            v-hasPermi="['system:file:remove']"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <pagination
      v-show="total>0"
      :total="total"
      v-model:page="queryParams.pageNum"
      v-model:limit="queryParams.pageSize"
      @pagination="getList"
    />

    <!-- 上传对话框 -->
    <el-dialog :title="title" v-model="open" width="400px" append-to-body>
      <el-upload
        ref="uploadRef"
        :limit="1"
        accept="*"
        :headers="upload.headers"
        :action="upload.url"
        :disabled="upload.isUploading"
        :auto-upload="true"
        drag
        :show-file-list="false"
        :http-request="customUpload"
      >
        <el-icon class="el-icon--upload"><upload-filled /></el-icon>
        <div class="el-upload__text">将文件拖到此处，或<em>点击上传</em></div>
      </el-upload>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="open = false">取 消</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="File">
import { listFile, delFile, uploadFile } from "@/api/system/file";
import { getToken } from "@/utils/auth";

const { proxy } = getCurrentInstance();

const fileList = ref([]);
const open = ref(false);
const loading = ref(true);
const showSearch = ref(true);
const ids = ref([]);
const single = ref(true);
const multiple = ref(true);
const total = ref(0);
const title = ref("");
const dateRange = ref([]);

const data = reactive({
  form: {},
  queryParams: {
    pageNum: 1,
    pageSize: 10,
    fileName: undefined,
    fileSuffix: undefined
  },
  upload: {
    // 是否禁用上传
    isUploading: false,
    // 设置上传的请求头部
    headers: { Authorization: "Bearer " + getToken() },
    // 上传的地址
    url: import.meta.env.VITE_APP_BASE_API + "/system/file/upload"
  }
});

const { queryParams, upload } = toRefs(data);

/** 查询文件列表 */
function getList() {
  loading.value = true;
  listFile(proxy.addDateRange(queryParams.value, dateRange.value)).then(response => {
    fileList.value = response.rows;
    total.value = response.total;
    loading.value = false;
  });
}

/** 搜索按钮操作 */
function handleQuery() {
  queryParams.value.pageNum = 1;
  getList();
}

/** 重置按钮操作 */
function resetQuery() {
  dateRange.value = [];
  proxy.resetForm("queryRef");
  handleQuery();
}

/** 多选框选中数据 */
function handleSelectionChange(selection) {
  ids.value = selection.map(item => item.fileId);
  single.value = selection.length != 1;
  multiple.value = !selection.length;
}

/** 新增按钮操作 */
function handleAdd() {
  open.value = true;
  title.value = "上传文件";
}

/** 自定义上传 */
function customUpload(options) {
    upload.value.isUploading = true;
    const formData = new FormData();
    formData.append("file", options.file);
    uploadFile(formData).then(response => {
        upload.value.isUploading = false;
        proxy.$modal.msgSuccess("上传成功");
        open.value = false;
        getList();
    }).catch(() => {
        upload.value.isUploading = false;
        proxy.$modal.msgError("上传失败");
    });
}

/** 删除按钮操作 */
function handleDelete(row) {
  const fileIds = row.fileId || ids.value;
  proxy.$modal.confirm('是否确认删除文件ID为"' + fileIds + '"的数据项？').then(function() {
    return delFile(fileIds);
  }).then(() => {
    getList();
    proxy.$modal.msgSuccess("删除成功");
  }).catch(() => {});
}

/** 下载文件 */
function handleDownload(row) {
    window.open(row.filePath, "_blank");
}

/** 格式化文件大小 */
function formatFileSize(size) {
    if (!size) return '0 B';
    if (size < 1024) return size + ' B';
    if (size < 1024 * 1024) return (size / 1024).toFixed(2) + ' KB';
    if (size < 1024 * 1024 * 1024) return (size / (1024 * 1024)).toFixed(2) + ' MB';
    return (size / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

/** 是否图片 */
function isImage(suffix) {
    if (!suffix) return false;
    return ['png', 'jpg', 'jpeg', 'gif', 'bmp'].includes(suffix.toLowerCase());
}

getList();
</script>
