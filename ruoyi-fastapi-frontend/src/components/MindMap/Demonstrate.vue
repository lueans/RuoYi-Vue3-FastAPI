<template>
  <div class="demonstrateContainer" :class="{ isDark: isDark }">
    <el-tooltip effect="dark" content="进入演示模式" placement="top">
      <div class="btn iconfont iconyanshibofang" @click="enterDemoMode"></div>
    </el-tooltip>
    <div
      class="exitDemonstrateBtn"
      @click="exit"
      ref="exitDemonstrateBtnRef"
      v-if="isEnterDemonstrate"
      @mousedown.stop
      @mousemove.stop
      @mouseup.stop
    >
      <span class="icon iconfont iconguanbi"></span>
    </div>
    <div
      class="stepBox"
      ref="stepBoxRef"
      v-if="isEnterDemonstrate"
      @mousedown.stop
      @mousemove.stop
      @mouseup.stop
    >
      <div class="jump" @click="prev" :class="{ disabled: curStepIndex <= 0 }">
        <span class="icon el-icon-back">
          <el-icon><ArrowLeft /></el-icon>
        </span>
      </div>
      <div class="step">{{ curStepIndex + 1 }} / {{ totalStep }}</div>
      <div
        class="jump"
        @click="next"
        :class="{ disabled: curStepIndex >= totalStep - 1 }"
      >
        <span class="icon el-icon-right">
          <el-icon><ArrowRight /></el-icon>
        </span>
      </div>
      <div class="input">
        <input
          type="text"
          v-model="inputStep"
          @keyup.enter.stop="onEnter"
          @keydown.stop
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import bus from './useEventBus'

const props = defineProps({
  mindMap: { type: Object, default: null },
  isDark: { type: Boolean, default: false }
})

const isEnterDemonstrate = ref(false)
const curStepIndex = ref(0)
const totalStep = ref(0)
const inputStep = ref('')
const exitDemonstrateBtnRef = ref(null)
const stepBoxRef = ref(null)

function enterDemoMode() {
  isEnterDemonstrate.value = true
  nextTick(() => {
    const el = document.querySelector('#mindMapContainer')
    if (el) {
      if (exitDemonstrateBtnRef.value) {
        el.appendChild(exitDemonstrateBtnRef.value)
      }
      if (stepBoxRef.value) {
        el.appendChild(stepBoxRef.value)
      }
    }
  })
  props.mindMap?.demonstrate?.enter()
}

function exit() {
  props.mindMap?.demonstrate?.exit()
}

function onExit() {
  isEnterDemonstrate.value = false
  curStepIndex.value = 0
  totalStep.value = 0
}

function onJump(index, total) {
  curStepIndex.value = index
  totalStep.value = total
}

function prev() {
  props.mindMap?.demonstrate?.prev()
}

function next() {
  props.mindMap?.demonstrate?.next()
}

function onEnter() {
  const num = Number(inputStep.value)
  if (Number.isNaN(num)) {
    inputStep.value = ''
  } else if (num >= 1 && num <= totalStep.value) {
    props.mindMap?.demonstrate?.jump(num - 1)
  }
}

onMounted(() => {
  bus.on('demonstrate_jump', onJump)
  bus.on('exit_demonstrate', onExit)
})

onBeforeUnmount(() => {
  bus.off('demonstrate_jump', onJump)
  bus.off('exit_demonstrate', onExit)
})
</script>

<style lang="less" scoped>
.demonstrateContainer {
  display: flex;
  align-items: center;

  &.isDark {
    .btn {
      color: hsla(0, 0%, 100%, 0.6);
    }
  }

  .item {
    margin-right: 12px;

    &:last-of-type {
      margin-right: 0;
    }
  }

  .btn {
    cursor: pointer;
    font-size: 24px;
  }
}

.exitDemonstrateBtn {
  position: absolute;
  right: 40px;
  top: 20px;
  cursor: pointer;
  z-index: 10001;
  pointer-events: all;

  .icon {
    font-size: 28px;
    color: #fff;
  }
}

.stepBox {
  position: absolute;
  right: 40px;
  bottom: 20px;
  pointer-events: all;
  z-index: 10001;
  display: flex;
  align-items: center;

  .step {
    color: #fff;
    margin: 0 12px;
  }

  .jump {
    color: #fff;
    cursor: pointer;

    &.disabled {
      cursor: not-allowed;
      color: #999;
    }
  }

  .input {
    margin-left: 12px;
    display: flex;
    align-items: center;

    input {
      width: 50px;
      height: 30px;
      text-align: center;
      background-color: transparent;
      border: 1px solid #999;
      outline: none;
      color: #fff;
    }
  }
}
</style>
