# Delta · bench-platform

## ADDED Requirements

### Requirement: 启动期清理失败须降级，不得使应用退出

平台在启动时执行的清理步骤（如回收上一个进程遗留的运行任务）SHALL 在失败时降级：
记录可诊断的日志并继续启动，MUST NOT 因清理失败而中止应用启动。

启动路径上的每一处日志调用 SHALL 使用本模块已定义的 logger。

#### Scenario: 清理抛异常时应用仍可用

- **WHEN** 启动期的遗留任务清理因数据库连接或约束冲突抛异常
- **THEN** 应用记录告警并完成启动，各页面可正常访问

#### Scenario: 降级分支里的符号必须已定义

- **WHEN** 清理的 `except` 分支引用一个模块级符号（如 logger）
- **THEN** 该符号在模块导入时已定义，不依赖正常路径是否执行过

> 实证：2026-11-21 `src/web/app.py` 的 `_reap_stale_generation_jobs` 在 `except`
> 分支使用未定义的 `logger`，正常启动与 CI 全绿；一旦清理失败即
> `NameError: name 'logger' is not defined` → `Application startup failed. Exiting.`
