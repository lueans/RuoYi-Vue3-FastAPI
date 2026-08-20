<template>
  <div class="demonstrateContainer" :class="{ isDark: isDark }">
    <el-tooltip v-if="!isEnterDemonstrate" effect="dark" content="进入演示模式" placement="top">
      <button
        ref="enterDemonstrateBtnRef"
        class="btn iconfont iconyanshibofang"
        type="button"
        aria-label="进入演示模式"
        :aria-busy="isEntering"
        :disabled="isEntering"
        @click="enterDemoMode"
      ></button>
    </el-tooltip>
    <button
      class="exitDemonstrateBtn"
      type="button"
      aria-label="退出演示模式"
      @click="exit"
      ref="exitDemonstrateBtnRef"
      v-if="isEnterDemonstrate"
      @mousedown.stop
      @mousemove.stop
      @mouseup.stop
    >
      <span class="icon iconfont iconguanbi"></span>
    </button>
    <div
      class="stepBox"
      ref="stepBoxRef"
      v-if="isEnterDemonstrate"
      role="toolbar"
      aria-label="演示控制"
      @mousedown.stop
      @mousemove.stop
      @mouseup.stop
    >
      <button class="jump" type="button" aria-label="上一页" :disabled="curStepIndex <= 0" @click="prev">
        <span class="icon el-icon-back">
          <el-icon><ArrowLeft /></el-icon>
        </span>
      </button>
      <div class="step" aria-live="polite">第 {{ curStepIndex + 1 }} / {{ totalStep }} 页</div>
      <button
        class="jump"
        type="button"
        aria-label="下一页"
        :disabled="curStepIndex >= totalStep - 1"
        @click="next"
      >
        <span class="icon el-icon-right">
          <el-icon><ArrowRight /></el-icon>
        </span>
      </button>
      <div class="input">
        <input
          type="number"
          inputmode="numeric"
          min="1"
          :max="totalStep"
          step="1"
          aria-label="跳转到演示页码"
          v-model="inputStep"
          @keyup.enter.stop="jumpToInputStep"
          @blur="normalizeInputStep"
          @keydown.stop
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import bus from './useEventBus'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'

const props = defineProps({
  mindMap: { type: Object, default: null },
  isDark: { type: Boolean, default: false }
})

const isEnterDemonstrate = ref(false)
const isEntering = ref(false)
const curStepIndex = ref(0)
const totalStep = ref(0)
const inputStep = ref('')
const exitDemonstrateBtnRef = ref(null)
const stepBoxRef = ref(null)
const enterDemonstrateBtnRef = ref(null)
let componentAlive = true
let enterRequestId = 0

function mountControlsIntoCanvas() {
  const mindMap = props.mindMap
  nextTick(() => {
    if (!componentAlive || props.mindMap !== mindMap) return
    const el = mindMap?.el
    if (el) {
      if (exitDemonstrateBtnRef.value) {
        el.appendChild(exitDemonstrateBtnRef.value)
      }
      if (stepBoxRef.value) {
        el.appendChild(stepBoxRef.value)
      }
      exitDemonstrateBtnRef.value?.focus()
    }
  })
}

async function enterDemoMode() {
  if (isEntering.value || isEnterDemonstrate.value) return
  const mindMap = props.mindMap
  if (!mindMap?.demonstrate?.enter) {
    ElMessage.warning('演示组件尚未就绪')
    return
  }
  const requestId = ++enterRequestId
  isEntering.value = true
  try {
    await mindMap.demonstrate.enter()
  } catch (error) {
    if (!isCurrentEnterRequest(requestId, mindMap)) return
    ElMessage.warning(error?.message || '无法进入演示模式')
  } finally {
    if (isCurrentEnterRequest(requestId, mindMap) && !isEnterDemonstrate.value) {
      isEntering.value = false
    }
  }
}

function isCurrentEnterRequest(requestId, mindMap) {
  return componentAlive
    && requestId === enterRequestId
    && props.mindMap === mindMap
}

function exit() {
  props.mindMap?.demonstrate?.exit()
}

function onExit(sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  isEnterDemonstrate.value = false
  isEntering.value = false
  curStepIndex.value = 0
  totalStep.value = 0
  inputStep.value = ''
  nextTick(() => enterDemonstrateBtnRef.value?.focus())
}

function onEnterDemonstrate(sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  if (!props.mindMap?.demonstrate?.isInDemonstrate) return
  isEnterDemonstrate.value = true
  isEntering.value = false
  mountControlsIntoCanvas()
}

function onJump(index, total, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  if (!props.mindMap?.demonstrate?.isInDemonstrate) return
  curStepIndex.value = index
  totalStep.value = total
  inputStep.value = String(index + 1)
}

function prev() {
  props.mindMap?.demonstrate?.prev()
}

function next() {
  props.mindMap?.demonstrate?.next()
}

function jumpToInputStep() {
  const num = Number(inputStep.value)
  if (Number.isInteger(num) && num >= 1 && num <= totalStep.value) {
    props.mindMap?.demonstrate?.jump(num - 1)
  } else {
    normalizeInputStep()
  }
}

function normalizeInputStep() {
  inputStep.value = totalStep.value ? String(curStepIndex.value + 1) : ''
}

onMounted(() => {
  bus.on('enter_demonstrate', onEnterDemonstrate)
  bus.on('demonstrate_jump', onJump)
  bus.on('exit_demonstrate', onExit)
})

onBeforeUnmount(() => {
  componentAlive = false
  enterRequestId++
  if (isEnterDemonstrate.value || isEntering.value) {
    props.mindMap?.demonstrate?.exit?.()
  }
  bus.off('enter_demonstrate', onEnterDemonstrate)
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
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
    font-size: 24px;

    &:disabled {
      cursor: progress;
      opacity: 0.45;
    }

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 4px;
      border-radius: 3px;
    }
  }
}

.exitDemonstrateBtn {
  position: absolute;
  right: 40px;
  top: 20px;
  cursor: pointer;
  z-index: 10001;
  pointer-events: all;
  padding: 0;
  border: 0;
  background: transparent;

  &:focus-visible {
    outline: 2px solid #fff;
    outline-offset: 4px;
    border-radius: 3px;
  }

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
    display: inline-flex;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;

    &:disabled {
      cursor: not-allowed;
      color: #999;
    }

    &:focus-visible {
      outline: 2px solid #fff;
      outline-offset: 4px;
      border-radius: 3px;
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
