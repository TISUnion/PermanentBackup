import collections
import os
import shutil
import time
import zipfile
from threading import Lock
from typing import List, Dict

from mcdreforged.api.all import *


class SlotInfo(Serializable):
	delete_protection: int = 0


class Configure(Serializable):
	size_display: bool = True
	turn_off_auto_save: bool = True
	ignore_session_lock: bool = True
	backup_path: str = './perma_backup'
	server_path: str = './server'
	world_names: List[str] = [
		'world'
	]
	# 0:guest 1:user 2:helper 3:admin 4:owner
	minimum_permission_level: Dict[str, int] = {
		'make': 2,
		'list': 0,
		'listall': 2
	}
	slots: List[SlotInfo] = [
		SlotInfo(delete_protection=0),  # 无保护
		SlotInfo(delete_protection=0),  # 无保护
		SlotInfo(delete_protection=0),  # 无保护
		SlotInfo(delete_protection=3 * 60 * 60),  # 三小时
		SlotInfo(delete_protection=3 * 24 * 60 * 60),  # 三天
	]


config: Configure
Prefix = '!!backup'
CONFIG_FILE = os.path.join('config', 'PermanentBackup.json')
HelpMessage = '''
§7------§rMCDR Permanent Backup§7------§r
一个创建永久备份的插件
§a【格式说明】§r
§7{0}§r 显示帮助信息
§7{0} make [<comment>]§r 创建一个备份。§7[<comment>]§r为可选注释信息
§7{0} list§r 显示最近的十个备份的信息
§7{0} listall§r 显示所有备份的信息
'''.strip().format(Prefix)
game_saved = False
plugin_unloaded = False
creating_backup = Lock()
'''
mcdr_root/
	server/
		world/
	perma_backup/
		backup_2020-04-29_20-08-11_comment.zip
'''


def info_message(source: CommandSource, msg: str, broadcast=False):
	for line in msg.splitlines():
		text = '[Permanent Backup] ' + line
		if broadcast and source.is_player:
			source.get_server().broadcast(text)
		else:
			source.reply(text)


def touch_backup_folder():
	if not os.path.isdir(config.backup_path):
		os.makedirs(config.backup_path)


def add_file(zipf, path, arcpath):
	for dir_path, dir_names, file_names in os.walk(path):
		for file_name in file_names:
			full_path = os.path.join(dir_path, file_name)
			arc_name = os.path.join(arcpath, full_path.replace(path, '', 1).lstrip(os.sep))
			zipf.write(full_path, arcname=arc_name)


def format_file_name(file_name):
	for c in ['/', '\\', ':', '*', '?', '"', '|', '<', '>']:
		file_name = file_name.replace(c, '')
	return file_name


@new_thread('Perma-Backup')
def create_backup(source: CommandSource, context: dict):
	comment = context.get('cmt', None)
	global creating_backup
	acquired = creating_backup.acquire(blocking=False)
	auto_save_on = True
	if not acquired:
		info_message(source, '§c正在备份中，请不要重复输入§r')
		return
	try:
		info_message(source, '备份中...请稍等', broadcast=True)
		start_time = time.time()

		# save world
		if config.turn_off_auto_save:
			source.get_server().execute('save-off')
			auto_save_on = False
		global game_saved
		game_saved = False
		source.get_server().execute('save-all flush')
		while True:
			time.sleep(0.01)
			if game_saved:
				break
			if plugin_unloaded:
				source.reply('§c插件卸载，备份中断！§r', broadcast=True)
				return

		# copy worlds
		def filter_ignore(path, files):
			return [file for file in files if file == 'session.lock' and config.ignore_session_lock]
		touch_backup_folder()
		for world in config.world_names:
			target_path = os.path.join(config.backup_path, world)
			if os.path.isdir(target_path):
				shutil.rmtree(target_path)
			shutil.copytree(os.path.join(config.server_path, world), target_path, ignore=filter_ignore)
		if not auto_save_on:
			source.get_server().execute('save-on')
			auto_save_on = True

		# find file name
		file_name_raw = os.path.join(config.backup_path, time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime()))
		if comment is not None:
			file_name_raw += '_' + format_file_name(comment)
		zip_file_name = file_name_raw
		counter = 0
		while os.path.isfile(zip_file_name + '.zip'):
			counter += 1
			zip_file_name = '{}_{}'.format(file_name_raw, counter)
		zip_file_name += '.zip'

		# zipping worlds
		info_message(source, '创建压缩文件§e{}§r中...'.format(os.path.basename(zip_file_name)), broadcast=True)
		zipf = zipfile.ZipFile(zip_file_name, 'w', zipfile.ZIP_DEFLATED)
		for world in config.world_names:
			add_file(zipf, os.path.join(config.backup_path, world), world)
		zipf.close()

		# cleaning worlds
		for world in config.world_names:
			shutil.rmtree(os.path.join(config.backup_path, world))

		info_message(source, '备份§a完成§r，耗时{}秒'.format(round(time.time() - start_time, 1)), broadcast=True)
	except Exception as e:
		info_message(source, '备份§a失败§r，错误代码{}'.format(e), broadcast=True)
		source.get_server().logger.exception('创建备份失败')
	finally:
		creating_backup.release()
		if config.turn_off_auto_save and not auto_save_on:
			source.get_server().execute('save-on')


def list_backup(source: CommandSource, context: dict, *, amount=10):
	amount = context.get('amount', amount)
	touch_backup_folder()
	arr = []
	for name in os.listdir(config.backup_path):
		file_name = os.path.join(config.backup_path, name)
		if os.path.isfile(file_name) and file_name.endswith('.zip'):
			arr.append(collections.namedtuple('T', 'name stat')(os.path.basename(file_name)[: -len('.zip')], os.stat(file_name)))
	arr.sort(key=lambda x: x.stat.st_mtime, reverse=True)
	info_message(source, '共有§6{}§r个备份'.format(len(arr)))
	if amount == -1:
		amount = len(arr)
	for i in range(min(amount, len(arr))):
		source.reply('§7{}.§r §e{} §r{}MB'.format(i + 1, arr[i].name, round(arr[i].stat.st_size / 2 ** 20, 1)))


def on_info(server, info):
	if not info.is_user:
		if info.content == 'Saved the game':
			global game_saved
			game_saved = True


def on_load(server: PluginServerInterface, old):
	global creating_backup, config
	if hasattr(old, 'creating_backup') and type(old.creating_backup) == type(creating_backup):
		creating_backup = old.creating_backup
	server.register_help_message(Prefix, '创建永久备份')
	config = server.load_config_simple(CONFIG_FILE, target_class=Configure, in_data_folder=False)
	register_command(server)


def on_unload(server: PluginServerInterface):
	global plugin_unloaded
	plugin_unloaded = True


def on_mcdr_stop(server: PluginServerInterface):
	if creating_backup.locked():
		server.logger.info('Waiting for up to 300s for permanent backup to complete')
		if creating_backup.acquire(timeout=300):
			creating_backup.release()


def register_command(server: PluginServerInterface):
	def permed_literal(literal: str):
		lvl = config.minimum_permission_level.get(literal, 0)
		return Literal(literal).requires(lambda src: src.has_permission(lvl), failure_message_getter=lambda: '§c权限不足！§r')

	server.register_command(
		Literal(Prefix).
		runs(lambda src: src.reply(HelpMessage)).
		on_error(UnknownCommand, lambda src: src.reply('参数错误！请输入§7{}§r以获取插件帮助'.format(Prefix)), handled=True).
		then(
			permed_literal('make').
			runs(create_backup).
			then(GreedyText('cmt').runs(create_backup))
		).
		then(
			permed_literal('list').
			runs(list_backup).
			then(Integer('amount').runs(list_backup))
		).
		then(
			permed_literal('listall').
			runs(lambda src: list_backup(src, {}, amount=-1))
		)
	)
