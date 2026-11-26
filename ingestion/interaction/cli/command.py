"""解析采集命令并调用注入的采集服务。"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from integration.llm import resolve_chat_model

from ...entity import AvatarIndex, MaterialIndex, Platform
from ...service import (
    AvatarService,
    BatchCollectMaterialParam,
    BatchProcessMaterialParam,
    CollectAndProcessMaterialParam,
    CollectMaterialParam,
    IngestionError,
    ListRemoteMaterialsParam,
    MaterialCollectAndProcessService,
    MaterialProcessService,
    MaterialService,
    ProcessMaterialParam,
)
from . import display

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AvatarRef(AvatarIndex):
    """把命令行提供的本地博主 ID 交给服务层。"""

    #: 项目内登记的博主 ID。
    avatar_id: int

    def get_avatar_index(self) -> int:
        """取得要查询的博主标识。

        :returns: 项目内登记的博主 ID。
        """
        return self.avatar_id


@dataclass(frozen=True)
class _MaterialRef(MaterialIndex):
    """把命令行提供的本地资料 ID 交给服务层。"""

    #: 已保存资料在项目内的 ID。
    material_id: int

    def get_material_index(self) -> int:
        """取得要查询或加工的资料标识。

        :returns: 已保存资料在项目内的 ID。
        """
        return self.material_id


class _StoreOnce(argparse.Action):
    """拒绝在单条命令中多次指定同一个目标选项。"""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        """保存单个目标，重复提供目标时报告参数错误。

        :param parser: 当前命令的参数解析器。
        :param namespace: 保存解析结果的命名空间。
        :param values: 已转换的单个目标值。
        :param option_string: 用户输入的选项名称。
        :raises SystemExit: 同一个选项重复出现。
        """
        if getattr(namespace, self.dest, None) is not None:
            parser.error(f"{option_string} 在此命令中只能指定一次。")
        setattr(namespace, self.dest, values)


def _non_negative_int(value: str) -> int:
    """解析不能小于零的整数选项。

    :param value: 命令行选项的原始文本。
    :returns: 解析出的非负整数。
    :raises argparse.ArgumentTypeError: 文本不是非负整数。
    """
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"必须是非负整数：{value}") from None
    if number < 0:
        raise argparse.ArgumentTypeError(f"必须是非负整数：{value}")
    return number


def _positive_int(value: str) -> int:
    """解析从 1 开始的分页选项。

    :param value: 页码或每页数量的原始文本。
    :returns: 解析出的正整数。
    :raises argparse.ArgumentTypeError: 文本不是正整数。
    """
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"必须是正整数：{value}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"必须是正整数：{value}")
    return number


def _add_avatar_options(parser: argparse.ArgumentParser, *, platform_required: bool = True) -> None:
    """为按博主查询的命令添加身份和平台选项。

    :param parser: 要添加选项的子命令解析器。
    :param platform_required: 是否必须指定来源平台。
    """
    parser.add_argument("--avatar-id", type=_non_negative_int, required=True, help="项目内登记的博主 ID")
    parser.add_argument(
        "--platform", type=Platform, choices=list(Platform), required=platform_required, help="来源平台"
    )


def _add_skip_option(parser: argparse.ArgumentParser, help_text: str) -> None:
    """登记已有结果的跳过开关及其否定选项。

    :param parser: 要添加开关的子命令解析器。
    :param help_text: 说明该命令检查的是原稿还是加工稿。
    """
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True, help=help_text)


def _build_parser() -> argparse.ArgumentParser:
    """构造采集模块的两组命令并登记服务分派信息。

    :returns: 已登记全部子命令的入口解析器。
    """
    parser = argparse.ArgumentParser(prog="python -m ingestion.interaction.cli", description="资料采集与加工")
    groups = parser.add_subparsers(dest="command_group", required=True)

    avatar = groups.add_parser("avatar", help="博主登记")
    avatar_commands = avatar.add_subparsers(dest="command_name", required=True)
    list_avatars = avatar_commands.add_parser("list", help="列出已登记的博主")
    list_avatars.set_defaults(service_name="AvatarService", handler=_list_avatars)

    material = groups.add_parser("material", help="资料浏览、采集与加工")
    material.set_defaults(service_name="MaterialService")
    material_commands = material.add_subparsers(dest="command_name", required=True)

    remote = material_commands.add_parser("list-remote", help="分页列出远端资料")
    _add_avatar_options(remote)
    remote.add_argument("--page", type=_positive_int, default=1, help="页码，默认 1")
    remote.add_argument("--page-size", type=_positive_int, help="每页条目数，默认使用来源平台配置")
    remote.add_argument("--collection-key", help="B 站合集标识，支持 ID、season:<ID>、series:<ID>")
    remote.set_defaults(handler=_list_remote_materials)

    local = material_commands.add_parser("list-local", help="列出本地资料")
    _add_avatar_options(local, platform_required=False)
    local.set_defaults(handler=_list_local_materials)

    show = material_commands.add_parser("show", help="查看本地资料详情")
    show.add_argument(
        "--material-id", type=_non_negative_int, action=_StoreOnce, required=True, help="本地资料 ID"
    )
    show.set_defaults(handler=_get_material)

    collect = material_commands.add_parser("collect", help="采集一份原始资料")
    _add_avatar_options(collect)
    collect.add_argument("--source-key", action=_StoreOnce, required=True, help="平台内容标识，例如 B 站 BV 号")
    _add_skip_option(collect, "默认跳过已有原稿的资料")
    collect.set_defaults(handler=_collect_material)

    collect_and_process = material_commands.add_parser("collect-and-process", help="采集一份资料后直接加工")
    _add_avatar_options(collect_and_process)
    collect_and_process.add_argument(
        "--source-key", action=_StoreOnce, required=True, help="平台内容标识，例如 B 站 BV 号",
    )
    collect_and_process.add_argument("--provider", help="模型供应商，例如 deepseek 或 tokenhub")
    collect_and_process.add_argument("--model", help="模型标识，默认使用 DeepSeek Flash")
    _add_skip_option(collect_and_process, "默认按阶段跳过已有原稿或加工稿")
    collect_and_process.set_defaults(
        service_name="MaterialCollectAndProcessService", handler=_collect_and_process_material,
    )

    batch_collect = material_commands.add_parser("batch-collect", help="采集多份原始资料")
    _add_avatar_options(batch_collect)
    batch_collect.add_argument(
        "--source-key", action="append", required=True, help="平台内容标识，例如 B 站 BV 号，可重复传入"
    )
    _add_skip_option(batch_collect, "默认逐项跳过已有原稿的资料")
    batch_collect.set_defaults(handler=_batch_collect_material)

    process = material_commands.add_parser("process", help="加工一份本地资料")
    process.add_argument(
        "--material-id", type=_non_negative_int, action=_StoreOnce, required=True, help="本地资料 ID"
    )
    _add_skip_option(process, "默认跳过已有加工稿的资料")
    process.set_defaults(service_name="MaterialProcessService", handler=_process_material)

    batch_process = material_commands.add_parser("batch-process", help="加工多份本地资料")
    batch_process.add_argument(
        "--material-id", type=_non_negative_int, action="append", required=True, help="本地资料 ID，可重复传入"
    )
    _add_skip_option(batch_process, "默认逐项跳过已有加工稿的资料")
    batch_process.set_defaults(service_name="MaterialProcessService", handler=_batch_process_material)
    return parser


async def _list_avatars(args: argparse.Namespace, service: AvatarService) -> int:
    """查询并显示当前登记的博主。

    :param args: 解析后的子命令参数。
    :param service: 注入的博主管理服务。
    :returns: 查询完成时返回 0。
    """
    display.show_avatars(await service.list_avatars())
    return 0


async def _list_remote_materials(args: argparse.Namespace, service: MaterialService) -> int:
    """查询并显示指定博主的一页远端资料。

    :param args: 博主、平台和分页选项。
    :param service: 注入的资料服务。
    :returns: 查询完成时返回 0。
    """
    param = ListRemoteMaterialsParam(page=args.page, page_size=args.page_size, collection_key=args.collection_key)
    page = await service.list_remote_materials(_AvatarRef(args.avatar_id), args.platform, param)
    display.show_remote_materials(page)
    return 0


async def _list_local_materials(args: argparse.Namespace, service: MaterialService) -> int:
    """按博主及可选平台显示已有本地资料。

    :param args: 博主索引和可选平台。
    :param service: 注入的资料服务。
    :returns: 查询完成时返回 0。
    """
    materials = await service.list_local_materials(_AvatarRef(args.avatar_id), args.platform)
    display.show_local_materials(materials)
    return 0


async def _get_material(args: argparse.Namespace, service: MaterialService) -> int:
    """显示资料详情或报告指定资料不存在。

    :param args: 包含本地资料 ID 的命令参数。
    :param service: 注入的资料服务。
    :returns: 找到资料时返回 0，否则返回 1。
    """
    material = await service.get_material(_MaterialRef(args.material_id))
    if material is None:
        logger.warning("资料详情不存在 material_id=%d", args.material_id)
        print(f"找不到资料 ID {args.material_id}。", file=sys.stderr)
        return 1
    display.show_material(material)
    return 0


async def _collect_material(args: argparse.Namespace, service: MaterialService) -> int:
    """将单条采集命令转换为服务调用。

    :param args: 博主、平台、内容标识及已有原稿的跳过开关。
    :param service: 注入的资料服务。
    :returns: 成功或正常跳过时返回 0，服务报告失败时返回 1。
    """
    param = CollectMaterialParam(source_key=args.source_key, skip_existing=args.skip_existing)
    result = await service.collect_material(_AvatarRef(args.avatar_id), args.platform, param)
    return display.show_results([result])


async def _collect_and_process_material(
    args: argparse.Namespace, service: MaterialCollectAndProcessService,
) -> int:
    """把一条 CLI 命令交给采集及加工服务。

    :param args: 博主、平台、内容标识、选定模型和跳过策略。
    :param service: 注入的采集并加工服务。
    :returns: 两阶段均成功、跳过或无需加工时返回 0，失败时返回 1。
    """
    selection = None
    if args.provider is not None or args.model is not None:
        selection = resolve_chat_model(provider=args.provider, model=args.model)
    param = CollectAndProcessMaterialParam(
        source_key=args.source_key, model_selection=selection, skip_existing=args.skip_existing,
    )
    result = await service.collect_and_process_material(_AvatarRef(args.avatar_id), args.platform, param)
    return display.show_collect_and_process_result(result)


async def _batch_collect_material(args: argparse.Namespace, service: MaterialService) -> int:
    """按提交顺序转交多份原始资料的采集请求。

    :param args: 博主、平台、有序内容标识及已有原稿的跳过开关。
    :param service: 注入的资料服务。
    :returns: 任一结果为失败时返回 1，否则返回 0。
    """
    param = BatchCollectMaterialParam(source_keys=args.source_key, skip_existing=args.skip_existing)
    results = await service.batch_collect_material(_AvatarRef(args.avatar_id), args.platform, param)
    return display.show_results(results)


async def _process_material(args: argparse.Namespace, service: MaterialProcessService) -> int:
    """将单条加工命令转换为服务调用。

    :param args: 资料 ID 和已有加工稿的跳过开关。
    :param service: 注入的资料加工服务。
    :returns: 成功、正常跳过或无需加工时返回 0，服务报告失败时返回 1。
    """
    param = ProcessMaterialParam(skip_existing=args.skip_existing)
    result = await service.process_material(_MaterialRef(args.material_id), param)
    return display.show_results([result])


async def _batch_process_material(args: argparse.Namespace, service: MaterialProcessService) -> int:
    """按提交顺序转交多份资料的加工请求。

    :param args: 有序的资料 ID 和已有加工稿的跳过开关。
    :param service: 注入的资料加工服务。
    :returns: 任一结果为失败时返回 1，否则返回 0。
    """
    param = BatchProcessMaterialParam(
        material_indexes=[_MaterialRef(material_id) for material_id in args.material_id],
        skip_existing=args.skip_existing,
    )
    results = await service.batch_process_material(param)
    return display.show_results(results)


def main(
    argv: Sequence[str] | None = None,
    *,
    avatar_service: AvatarService | None = None,
    material_service: MaterialService | None = None,
    material_process_service: MaterialProcessService | None = None,
    material_collect_and_process_service: MaterialCollectAndProcessService | None = None,
) -> int:
    """解析命令并在单个事件循环中调用对应服务。

    :param argv: 命令参数。为 None 时读取进程参数。
    :param avatar_service: 注入的博主管理服务。为 None 时只能查看其命令帮助。
    :param material_service: 注入的资料服务。为 None 时可查看其命令帮助。
    :param material_process_service: 注入的资料加工服务。为 None 时可查看其命令帮助。
    :param material_collect_and_process_service: 注入的采集并加工服务。为 None 时可查看其命令帮助。
    :returns: 成功或帮助返回 0，业务失败返回 1，命令参数错误返回 2。
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as error:
        # argparse 打印帮助或参数错误后会退出，这里把退出码交给调用方。
        exit_code = int(error.code)
        if exit_code != 0:
            logger.warning("命令参数校验失败 exit_code=%d", exit_code)
        return exit_code

    services = {
        "AvatarService": avatar_service,
        "MaterialService": material_service,
        "MaterialProcessService": material_process_service,
        "MaterialCollectAndProcessService": material_collect_and_process_service,
    }
    command = f"{args.command_group} {args.command_name}"
    started = perf_counter()
    # 只记录解析器定义的命令名，原始参数可能含有外部输入。
    logger.info("命令开始 command=%s service=%s", command, args.service_name)
    service = services[args.service_name]
    if service is None:
        print(f"当前命令需要接入 {args.service_name}。", file=sys.stderr)
        logger.warning("命令缺少服务 command=%s service=%s", command, args.service_name)
        exit_code = 1
    else:
        try:
            exit_code = asyncio.run(args.handler(args, service))
        except (KeyError, ValueError, IngestionError) as error:
            logger.warning("命令执行失败 command=%s error_type=%s", command, type(error).__name__)
            print(f"操作失败：{error}", file=sys.stderr)
            exit_code = 1
        except KeyboardInterrupt:
            logger.warning("命令被中断 command=%s elapsed=%.3fs", command, perf_counter() - started)
            raise
        except Exception as error:
            logger.error("命令异常退出 command=%s error_type=%s elapsed=%.3fs",
                         command, type(error).__name__, perf_counter() - started)
            raise
    logger.info("命令结束 command=%s exit_code=%d elapsed=%.3fs", command, exit_code, perf_counter() - started)
    return exit_code
