<template>
  <el-select
    v-model="selectedValue"
    :placeholder="placeholder"
    filterable
    clearable
    :filter-method="filterUsers"
    @change="handleChange"
    @clear="handleClear"
  >
    <el-option
      v-for="user in filteredUsers"
      :key="user.userId"
      :label="user.nickName"
      :value="user.userName"
    >
      <div style="display: flex; align-items: center; padding: 2px 0;">
        <el-avatar :size="28" :src="getAvatarUrl(user.avatar)" style="flex-shrink: 0;">
          {{ user.nickName?.charAt(0) }}
        </el-avatar>
        <div style="margin-left: 10px; line-height: 1.3; overflow: hidden;">
          <div style="font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ user.nickName }}</div>
          <div style="font-size: 11px; color: #999; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ user.userName }}</div>
        </div>
      </div>
    </el-option>
  </el-select>
</template>

<script setup>
import { listUserOption } from "@/api/system/user";

const props = defineProps({
  modelValue: {
    type: String,
    default: ""
  },
  placeholder: {
    type: String,
    default: "请选择用户"
  }
});

const emit = defineEmits(["update:modelValue"]);

const baseApi = import.meta.env.VITE_APP_BASE_API;
const defaultAvatar = new URL("@/assets/images/profile.jpg", import.meta.url).href;
const userList = ref([]);
const filteredUsers = ref([]);
const selectedValue = ref(props.modelValue);

watch(() => props.modelValue, (val) => {
  selectedValue.value = val;
});

function getAvatarUrl(avatar) {
  if (!avatar) return defaultAvatar;
  if (avatar.startsWith("http")) return avatar;
  return baseApi + avatar;
}

function filterUsers(query) {
  if (!query) {
    filteredUsers.value = userList.value;
    return;
  }
  const keyword = query.toLowerCase();
  filteredUsers.value = userList.value.filter(user =>
    (user.userName && user.userName.toLowerCase().includes(keyword)) ||
    (user.nickName && user.nickName.toLowerCase().includes(keyword))
  );
}

function handleChange(val) {
  emit("update:modelValue", val);
}

function handleClear() {
  emit("update:modelValue", "");
}

async function loadUsers() {
  const res = await listUserOption();
  userList.value = res.data || [];
  filteredUsers.value = userList.value;
}

loadUsers();
</script>
