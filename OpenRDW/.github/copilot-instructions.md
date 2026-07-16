## 快速说明（面向 AI 编码代理）

这是一个基于 Unity 的重定向行走研究项目（OpenRDW）。下面的说明帮助你快速上手代码修改、实现算法、以及避免常见坑。

### 项目要点
- 单一配置中心：`Assets/OpenRDW/Scripts/Others/GlobalConfiguration.cs` 保存全局实验参数（移动模式、gain 范围、tracking space、networking 等）。
- 每个 avatar 有一组组件：`RedirectionManager`（`Assets/OpenRDW/Scripts/Redirection/RedirectionManager.cs`）+ `MovementManager`（`Assets/OpenRDW/Scripts/Movement/MovementManager.cs`）。
- 算法扩展点：`Redirector` 和 `Resetter` 为抽象基类，位于 `Assets/OpenRDW/Scripts/Redirection/Redirectors/Redirector.cs` 和 `Assets/OpenRDW/Scripts/Redirection/Resetters/Resetter.cs`。
- 网络同步：使用 Photon PUN（由 `Assets/OpenRDW/Scripts/Networking/NetworkManager.cs` 管理）。

### 常见工作流 & 约定
- 切换 Redirector/Resetter：不要直接 new；使用 `RedirectionManager.UpdateRedirector(Type)` 与 `UpdateResetter(Type)`（内部通过 `gameObject.AddComponent(type)` / `Destroy` 动态管理）。更新映射需修改 `RedirectionManager.RedirectorChoiceToRedirector`、`RedirectorToRedirectorChoice`、`DecodeRedirector`（文件中注明“modify these three functions when adding a new redirector”）。
- 关键生命周期：
  - 初始化：`RedirectionManager.Awake()` -> `GetRedirector()` / `GetResetter()` -> `resetter.Initialize()`
  - 每步执行：`MovementManager.MakeOneStepMovement()` 与 `RedirectionManager.MakeOneStepRedirection()` 分别驱动模拟与重定向逻辑
  - 新增算法：继承 `Redirector` 实现 `InjectRedirection()` 或继承 `Resetter` 实现 `IsResetRequired/InitializeReset/InjectResetting/EndReset`。
- 坑位提醒：`MovementManager.LoadData()` 注释指出“必须先设置 user，再设置 redirection recipient”，即对象初始化/赋值顺序会影响用户位置重置。

### 代码风格和约定（可从代码中直接发现）
- 坐标/方向：大量使用 `Utilities.FlattenedPos3D/FlattenedDir3D` 与 `GetRelativePosition`，在实现空间相关算法时务必沿用这些工具函数以保持一致。
- 时间：实验可能使用仿真时间（`globalConfiguration.useSimulationTime` 与 `targetFPS`），测试时注意 `GlobalConfiguration.GetDeltaTime()` 的语义。
- 日志：所有重要事件通过 `globalConfiguration.statisticsLogger.Event_*` 记录（例如 rotation/translation/curvature gain），修改相关统计请同时更新 logger 使用处。

### 添加新 Redirector/Resetter 的具体示例
1. 新建 `Assets/OpenRDW/Scripts/Redirection/Redirectors/MyRedirector.cs`，继承 `Redirector`，实现 `InjectRedirection()`。使用 `InjectRotation/InjectTranslation/InjectCurvature` 应用变换并自动记录 gain。 
2. 在 `RedirectionManager.RedirectorChoiceToRedirector`、`RedirectorToRedirectorChoice`、`DecodeRedirector` 三处添加映射。 
3. 可以通过场景中对应 avatar 的 `RedirectionManager` 调用 `UpdateRedirector(typeof(MyRedirector))` 来热切换。

### 与外部依赖相关
- Photon PUN：`NetworkManager` 引用了 `Photon.Pun`，网络模式下 Avatar 同步由 `avatarNetworkingTransformPrefab` 管理。确保在 Unity 包管理器或 Plugins 中安装并配置 Photon。

### 测试 / 运行提示
- 打开 Unity（建议使用与项目兼容的 Unity 版本），加载工程后在 Inspector 修改 `GlobalConfiguration`（例如把 `movementController` 设为 `AutoPilot`，启用 `runInBackstage` 或 `useSimulationTime`）并按 Play 做快速验证。
- 单 avatar 调试：在场景中选中某个 `Redirected Avatar`（位于 `GlobalConfiguration.redirectedAvatars` 中），在 Inspector 手动调用 `UpdateRedirector`/`UpdateResetter` 或在 Play 模式下改变 `redirectorChoice`/`resetterChoice`。

如果你想要我把这份指南更紧凑或补上具体的类/方法引用示例（例如 `InjectRotation` 的调用链、statistics logger 的事件定义位置等），告诉我你希望强化的部分，我会迭代更新。 
