# Python 代码规范

通用的模块边界、中文注释和测试目录约定见[项目代码规范](项目代码规范.md)。

## 包和文件

- `__init__.py` 按需创建，用于明确导出公开接口、完成包初始化或满足必要的工具要求。仅用于占位的 `__init__.py`，包括只有一句目录说明的文件，可以省略。

## 接口与命名

- 类名使用 `CapWords`。字段、参数和方法名使用 `snake_case`，例如 `source_key`、`avatar_index` 和 `batch_collect_material`。
- 服务接口和身份索引用 `typing.Protocol` 定义。身份索引公开对应的取值方法，例如 `get_avatar_index() -> int` 或 `get_material_index() -> int`。实体及相应的服务输出通过这些方法提供本地 ID。
- 无业务返回值的异步或同步方法使用 `-> None`。在文档字符串中用 `:raises ErrorType:` 声明调用方需要处理的异常及触发条件。单条查询允许查无资料时，使用 `T | None`，并在 `:returns:` 中说明 `None` 的含义。列表查询无匹配结果时返回空列表。

## 文档字符串

- 每个类、函数和方法都写文档字符串，包括私有辅助函数和测试方法。首行概述用途，正文说明调用方需要知道的特殊行为。数据类说明它表达的内容和适用范围。
- 统一使用 Sphinx 的 reStructuredText 字段 `:param name:`、`:returns:`、`:raises ErrorType:` 标记参数、返回值和调用方需要处理的异常。字段标记和参数名使用英文，说明使用中文。参数按签名顺序列出，注明单位、默认值及可空含义。省略 `self`、`cls` 和无值返回的 `:returns:`。类型以签名中的类型标注为准。 [PEP 257](https://peps.python.org/pep-0257/) · [Sphinx 字段说明](https://www.sphinx-doc.org/en/master/usage/domains/python.html#info-field-lists)
- 每个类字段在声明正上方写中文 `#:` 字段注释。说明值的业务含义及必要约定，类型以字段的类型标注为准。Sphinx autodoc 可读取这种字段注释。 [Sphinx 字段注释](https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#doc-comments-and-docstrings)

### 在 PyCharm 中生成和检查

1. 打开 `Settings → Tools → Python Integrated Tools`，将 `Docstring format` 设置为 `reStructuredText`。
2. 在函数或方法体首行输入三引号后按回车，让 PyCharm 根据签名生成文档字符串骨架。补写中文说明，以及编辑器无法判断的返回含义、异常和特殊行为。
3. 使用 `Quick Documentation` 检查渲染效果。修改函数签名后，同步核对参数字段。 [PyCharm 文档字符串设置](https://www.jetbrains.com/help/pycharm/settings-tools-python-integrated-tools.html)

## 单元测试

- 使用 `unittest` 执行测试。递归枚举模块级 `test/` 下的 `test_*.py` 文件，将路径传给 `unittest`。测试目录可以省略 `__init__.py`。通过打包规则将模块级测试目录排除在发布包之外。
