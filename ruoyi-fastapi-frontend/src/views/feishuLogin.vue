<template>
  <div class="feishu-login">
    <div class="status">{{ statusText }}</div>
  </div>
</template>

<script setup>
import { feishuLogin } from "@/api/login";
import { setToken } from "@/utils/auth";
import useUserStore from '@/store/modules/user'

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();
const statusText = ref("正在处理飞书登录...");

onMounted(() => {
  const code = route.query.code;
  if (!code) {
    statusText.value = "缺少code参数";
    return;
  }
  feishuLogin(code).then(res => {
    const token = res.token;
    if (token) {
      setToken(token);
      userStore.token = token;
      userStore.getInfo().then(() => {
        statusText.value = "登录成功，正在跳转...";
        router.replace({ path: "/" });
      })
    } else {
      statusText.value = "登录失败";
    }
  }).catch(() => {
    statusText.value = "登录失败";
  })
})
</script>

<style scoped>
.feishu-login {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
.status {
  color: #606266;
}
</style>
