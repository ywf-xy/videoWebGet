import { createPinia } from 'pinia'
import { createApp } from 'vue'

import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

// 按需注册图标（只引入实际用到的 39 个，避免把整包 ~200KB 图标打进 bundle）
import {
  Aim,
  Back,
  Box,
  Calendar,
  CircleCheck,
  Coin,
  Compass,
  Cpu,
  DataLine,
  Delete,
  Document,
  Download,
  Expand,
  Files,
  Fold,
  FolderAdd,
  FolderOpened,
  HomeFilled,
  Link,
  List,
  MagicStick,
  Odometer,
  Picture,
  Plus,
  Pointer,
  QuestionFilled,
  Refresh,
  RefreshLeft,
  RefreshRight,
  Search,
  Setting,
  Sort,
  Sunny,
  TrendCharts,
  Upload,
  UploadFilled,
  VideoCamera,
  VideoPause,
  VideoPlay,
  WarningFilled,
} from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './styles/index.scss'

/** 图标注册表：模板里通过 <component :is="'Setting'" /> / icon="Setting" 动态引用 */
const ICONS = {
  Aim,
  Back,
  Box,
  Calendar,
  CircleCheck,
  Coin,
  Compass,
  Cpu,
  DataLine,
  Delete,
  Document,
  Download,
  Expand,
  Files,
  Fold,
  FolderAdd,
  FolderOpened,
  HomeFilled,
  Link,
  List,
  MagicStick,
  Odometer,
  Picture,
  Plus,
  Pointer,
  QuestionFilled,
  Refresh,
  RefreshLeft,
  RefreshRight,
  Search,
  Setting,
  Sort,
  Sunny,
  TrendCharts,
  Upload,
  UploadFilled,
  VideoCamera,
  VideoPause,
  VideoPlay,
  WarningFilled,
}

const app = createApp(App)

for (const [name, component] of Object.entries(ICONS)) {
  app.component(name, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
