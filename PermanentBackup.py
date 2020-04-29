# coding: utf8
import collections
import copy
import json
import os
import shutil
import time
import zipfile
from threading import Lock

Prefix = '!!backup'
BackupPath = 'perma_backup'
TurnOffAutoSave = True
WorldNames = [
	'world',
]
# 0:guest 1:user 2:helper 3:admin
MinimumPermissionLevel = {
	'make': 2,
	'list': 0,
}
ServerPath = './server'
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


def info_message(server, info, msg, broadcast=False):
	for line in msg.splitlines():
		text = '[Permanent Backup] ' + line
		if broadcast and info.is_player:
			server.say(text)
		else:
			server.reply(info, text)


def touch_backup_folder():
	if not os.path.isdir(BackupPath):
		os.makedirs(BackupPath)


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


def create_backup(server, info, comment=''):
	global creating_backup
	acquired = creating_backup.acquire(blocking=False)
	if not acquired:
		info_message(server, info, '§c正在备份中，请不要重复输入§r')
		return
	try:
		info_message(server, info, '备份中...请稍等', broadcast=True)
		start_time = time.time()

		# save world
		if TurnOffAutoSave:
			server.execute('save-off')
		global game_saved
		game_saved = False
		server.execute('save-all')
		while True:
			time.sleep(0.01)
			if game_saved:
				break
			if plugin_unloaded:
				server.reply(info, '§c插件卸载，备份中断！§r', broadcast=True)
				return

		# copy worlds
		touch_backup_folder()
		for world in WorldNames:
			shutil.copytree(os.path.join(ServerPath, world), os.path.join(BackupPath, world))

		# find file name
		file_name_raw = os.path.join(BackupPath, time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime()))
		if comment != '':
			file_name_raw += '_' + format_file_name(comment)
		zip_file_name = file_name_raw
		counter = 0
		while os.path.isfile(zip_file_name + '.zip'):
			counter += 1
			zip_file_name = '{}_{}'.format(file_name_raw, counter)
		zip_file_name += '.zip'

		# zipping worlds
		info_message(server, info, '创建压缩文件§e{}§r中...'.format(os.path.basename(zip_file_name)), broadcast=True)
		zipf = zipfile.ZipFile(zip_file_name, 'w', zipfile.ZIP_DEFLATED)
		for world in WorldNames:
			add_file(zipf, os.path.join(BackupPath, world), world)
		zipf.close()

		# cleaning worlds
		for world in WorldNames:
			shutil.rmtree(os.path.join(BackupPath, world))

		info_message(server, info, '备份§a完成§r，耗时{}秒'.format(round(time.time() - start_time, 1)), broadcast=True)
	except Exception as e:
		info_message(server, info, '备份§a失败§r，错误代码{}'.format(e), broadcast=True)
	finally:
		creating_backup.release()
		if TurnOffAutoSave:
			server.execute('save-on')


def list_backup(server, info, amount=10):
	touch_backup_folder()
	arr = []
	for name in os.listdir(BackupPath):
		file_name = os.path.join(BackupPath, name)
		if os.path.isfile(file_name) and file_name.endswith('.zip'):
			arr.append(collections.namedtuple('T', 'name stat')(os.path.basename(file_name)[: -len('.zip')], os.stat(file_name)))
	arr.sort(key=lambda x: x.stat.st_mtime, reverse=True)
	info_message(server, info, '共有§6{}§r个备份'.format(len(arr)))
	if amount == -1:
		amount = len(arr)
	for i in range(min(amount, len(arr))):
		server.reply(info, '§7{}.§r §e{} §r{}MB'.format(i + 1, arr[i].name, round(arr[i].stat.st_size / 2 ** 20, 1)))


def on_info(server, info):
	if not info.is_user:
		if info.content == 'Saved the game':
			global game_saved
			game_saved = True
		return

	command = info.content.split()
	cmd_len = len(command)
	if cmd_len == 0 or command[0] != Prefix:
		return

	# MCDR permission check
	global MinimumPermissionLevel
	if cmd_len > 1 and command[1] in MinimumPermissionLevel.keys():
		if server.get_permission_level(info) < MinimumPermissionLevel[command[1]]:
			server.reply(info, '§c权限不足！§r')
			return

	# !!backup
	if cmd_len == 1:
		server.reply(info, HelpMessage)
		return

	# !!backup make [<comment>]
	elif cmd_len >= 2 and command[1] == 'make':
		comment = info.content.replace('{} make'.format(Prefix), '', 1).lstrip(' ') if cmd_len > 2 else ''
		create_backup(server, info, comment)

	# !!backup list
	elif cmd_len == 2 and command[1] == 'list':
		list_backup(server, info, 10)

	# !!backup listall
	elif cmd_len == 2 and command[1] == 'listall':
		list_backup(server, info, -1)

	else:
		server.reply(info, '参数错误！请输入§7{}§r以获取插件帮助'.format(Prefix))


def on_load(server, old):
	server.add_help_message(Prefix, '创建永久备份')


def on_unload(server):
	global plugin_unloaded
	plugin_unloaded = True
