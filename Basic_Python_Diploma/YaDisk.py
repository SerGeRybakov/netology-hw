"""
    Класс YaDisk - основной класс программы, содержащий в себе все методы для работы с такими сущностями Яндекс.Диска
    как папки и файлы.
    Классы YaFile и YaFolder - наследники класса YaFile и YaDisk. Они не имеют собственных методов, но имеют все
    атрибуты, присущие файлам и папкам, хранящимся на Яндекс.Диске.

    Основные методы для работы с этими сущностями являются:
     - create_folder,
     - find_biggest,
     - delete,
     - download,
     - upload,
     - zip_file.
     Основные методы влияют на файлы и папки непосредственным образом. Поэтому они должны быть унаследованы
     экземплярами классов YaFile и YaFolder.

     Вспомогательными методами являются:
     - _parse_catalogues,
     - print_all,
     - reload,
     - top10.
     Данные методы не влияют непосредственно на сами файлы и папки, а лишь собирают и/или выводят обобщенную
     статистическую информацию о файлах или папках. Вероятно, что такие методы не должны наследоваться экземплярами
     классов YaFile и YaFolder. При этом метод _parse_catalogues автоматически инициирует экземпляры классов YaFile и
     YaFolder с тем, чтобы программа имела полную информацию о текущем содержимом облака, а метод reload пересобирает
     эту информацию каждый раз, когда содержимое облака должно измениться после использования основных методов, влияющих
     на такое содержимое.

     В то же время, программа не предполагает непосредственных операций с экземплярами классов YaFile и YaFolder.
     На старте программы инициируется единственный экзепляр класса YaDisk, который обращается присущими ему методами с
     экземплярами классов YaFile и YaFolder - получает, обрабатывает, выводит информацию о всех них или о каждом
     отдельном экземпляре, а также непосредственно влияет на них тем или иным образом.

     Кроме этого, в целях избежания дублирования кода, функция __repr__ перегружена из класса YaDisk с тем, чтобы
     экземпляры наследников этого класса выводились на печать правильно (с моей точки зрения).
     См. комментарий к __repr__.
     """

import json
import os
import sys
import zipfile
from datetime import datetime

import requests
from tqdm import tqdm
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor


def track_upload_progress(pbar):
    prev_value = 0

    def callback(monitor):
        nonlocal prev_value
        diff = monitor.bytes_read - prev_value
        prev_value = monitor.bytes_read
        pbar.update(diff)

    return callback


class YaDisk:
    """Класс определяет атрибуты Яндекс.Диска (файлы и папки) и методы работы с ними"""

    def __init__(self, token):
        self.name = None
        self.all_files = []
        self.all_folders = []
        self.token = token
        self.URL = "https://cloud-api.yandex.net/v1/disk/resources"
        self.params = {"path": '/'}
        self.headers = {"port": "443", "Authorization": f"OAuth {self.token}"}
        print("Загрузка содержимого Я.Диска:")
        self._parse_catalogues()

    # noinspection Pylint
    def __repr__(self):
        return self.name

    def _parse_catalogues(self, path="/"):
        """Метод получает информацию обо всех файлах и папках на Яндекс.Диске"""
        self._point()
        yadisk_size = 0
        param = {"path": path}
        response = requests.get(self.URL, params=param, headers=self.headers)
        # try:
        for item in response.json()['_embedded']['items']:
            if item['type'] == "dir":
                folder_size = self._parse_catalogues(item["path"])
                yadisk_size += folder_size
                fsize = {"size": folder_size}
                item.update(fsize)
                self.all_folders.append(YaFolder(item))
            else:
                yadisk_size += item["size"]
                self.all_files.append(YaFile(item))
        return yadisk_size

    @staticmethod
    def _point():
        """Метод симулирует работу прогресс-бара: выводит одну точку на каждой итерации"""
        sys.stdout.write('.')
        sys.stdout.flush()

    @staticmethod
    def _size(item):
        size = int(round(item.size / 1024, 0))
        if size > 100000:
            size = str(round(size / 1024 ** 2, 2)) + " GB"
        elif 100000 > size > 1000:
            size = str(round(size / 1024, 2)) + " MB"
        else:
            size = str(size) + " KB"
        return size

    def create_folder(self, folder_name, path=None):
        """метод создает папку на яндекс.диске с заданным именем"""

        def _create(_param):
            put = requests.put(self.URL, headers=self.headers, params=_param)
            try:
                return put.status_code, put.json()["href"]
            except KeyError:
                return put.status_code, put.json()["message"]

        if path is None:
            print("Текущий список папок:")
            for num, dir in enumerate(self.all_folders):
                print("dir <index>" + str(num) + ".", dir)
            print("\nЕсли вы хотите создать папку в корне диска - нажмите Enter.\n"
                  "Если вы хотите создать папку внутри другой папки - введите индекс соответствующей папки.\n")
            tree = input('Введите ответ?')
            if not tree:
                param = {"path": folder_name}
            else:
                param = {"path": self.all_folders[int(tree)].path + "/" + folder_name}
        else:
            param = {"path": path}
        test = requests.get(self.URL, headers=self.headers, params=param)
        if test.status_code == 404:
            creator = _create(param)
            if creator[0] == 201:
                print(f'Папка "{folder_name}" успешно создана на Яндекс.Диске')
                print()
            else:
                print(creator)
                print()
        elif test.status_code == 200:
            print(f'Папка "{folder_name}" уже существует на Яндекс.Диске')
            print()
        else:
            print(test)

        self.reload()
        print("Текущий список папок:")
        self.print_all('folder')

    def delete(self, objects):
        """Метод удаляет папку или файл с яндекс.диска в корзину или навсегда"""

        def _check_existance(param):
            test = requests.get(self.URL, headers=self.headers, params=param)
            while test.status_code != 404:
                test = requests.get(self.URL, headers=self.headers, params=param)
            return "OK"

        print("Удаляем", objects)
        print("\nДля удаления объекта(-ов) в Корзину просто нажмите Enter.\n"
              "Для полного удаления объекта(-ов) без возможности восстановления введите 1.")
        permanent = input("Введите ответ: ")
        perm_del = ''
        if permanent == "1":
            perm_del = {"permanently": "true"}

        if isinstance(objects, list):
            for obj in tqdm(objects):
                param = {'path': obj.path}
                if perm_del:
                    param.update(perm_del)
                put = requests.delete(self.URL, headers=self.headers, params=param)
                if put.status_code >= 300:
                    return put.status_code, put.json()
                _check_existance(param)
        else:
            param = {'path': objects.path}
            if perm_del:
                param.update(perm_del)
            put = requests.delete(self.URL, headers=self.headers, params=param)
            if put.status_code >= 300:
                return put.status_code, put.json()
            _check_existance(param)

        if isinstance(objects, list):
            string = ", ".join(obj.name for obj in objects)
        else:
            string = objects
        self.reload()
        for num, dir in enumerate(self.all_folders):
            print("dir" + str(num) + ".", dir)
        print()

        if perm_del:
            return f'\nОбъекты {string} успешно удалены с Яндекс.Диска.\n'
        else:
            return f'\nОбъекты {string} успешно удалены в Корзину.\n'

    def download(self, item):
        """Метод скачивает на жесткий диск файл или папку"""
        try:
            item_name = item.path.split('disk:/')[-1]
            item_type = item.type
            item_path = item.path
            item_title = item.name
        except AttributeError:
            item_name = item['path'].split('disk:/')[-1]
            item_type = item['type']
            item_path = item['path']
            item_title = item['name']

        if item_type == "dir":
            target_folder = os.path.abspath(os.path.join('downloads', item_name))
            print(target_folder)
            try:
                os.makedirs(target_folder, exist_ok=True)
            except FileExistsError:
                return "Файл уже существует на диске"
        else:
            target_folder = os.path.abspath(os.path.join('downloads', item_name.split(item_title)[0]))
            print(target_folder)
            os.makedirs(target_folder, exist_ok=True)
            file_to_download = requests.get(item.link)
            with open(os.path.join(target_folder, item.name), 'wb') as file:
                file.write(file_to_download.content)

        param = {'path': item_path}
        response = requests.get(self.URL, params=param, headers=self.headers).json()
        try:
            for new_item in response['_embedded']['items']:
                if new_item['type'] == 'dir':
                    self.download(new_item)

                else:
                    file_to_download = requests.get(new_item["file"], stream=True)
                    total = new_item["size"]
                    with open(os.path.join(target_folder, new_item["name"]), 'wb') as file, tqdm(
                            desc=new_item["name"],
                            total=total,
                            unit='iB',
                            unit_scale=True,
                            unit_divisor=1024,
                    ) as bar:
                        for data in file_to_download.iter_content(chunk_size=1024):
                            size = file.write(data)
                            bar.update(size)
            return f'Папка "{item_title}" успешно скачана'

        except KeyError:
            file_to_download = requests.get(response["file"], stream=True)
            total = response["size"]
            with open(os.path.join(target_folder, response["name"]), 'wb') as file, tqdm(
                    desc=response["name"],
                    total=total,
                    unit='iB',
                    unit_scale=True,
                    unit_divisor=1024,
            ) as bar:
                for data in file_to_download.iter_content(chunk_size=1024):
                    size = file.write(data)
                    bar.update(size)
        return f'Файл "{item_title}" успешно скачан'

    def find_biggest(self, obj_type=None):
        """Метод выводит на экран папку или файл с самым большим размером.
        Для этого необходимо передать аргумент 'obj_type': либо 'file', либо 'folder'."""
        call = ""
        lst = None
        filename = None
        if (obj_type is None) or (obj_type != 'file' and obj_type != 'folder'):
            return print(self.find_biggest.__doc__)
        else:
            if obj_type == 'file':
                lst = self.all_files
                filename = "biggest_file_info.json"
                call = 'файлом'
            elif obj_type == 'folder':
                lst = self.all_folders
                filename = "biggest_folder_info.json"
                call = 'каталогом'
        max_size_object = max(lst, key=lambda obj: obj.size)
        with open(filename, "w", encoding="UTF-8") as file:
            json.dump({max_size_object.name: max_size_object.size}, file)
        print(f'Самым большим {call} является "{max_size_object.name}" - {self._size(max_size_object)}.')
        return max_size_object

    def print_all(self, obj_type=None):
        """Метод выводит на экран все папки или файлы, имеющиеся на Яндекс.Диске.
        Для этого необходимо передать аргумент 'obj_type': либо 'file', либо 'folder'."""
        collection = None
        if (obj_type is None) or (obj_type != 'file' and obj_type != 'folder'):
            return print(self.top10.__doc__)
        else:
            if obj_type == 'file':
                collection = self.all_files
            elif obj_type == 'folder':
                collection = self.all_folders
            for num, file in enumerate(collection):
                print(obj_type + " " + str(num) + ".", file, file.size)
        return collection

    def reload(self):
        """Метод обновляет информацию обо всех файлах и папках на Яндекс.Диске"""
        self.all_folders = []
        self.all_files = []
        print("Обновление содержимого Я.Диска:")
        self._parse_catalogues()

    def top10(self, obj_type=None):
        """Метод выводит на экран топ-10 самых больших папок или файлов.
        Для этого необходимо передать аргумент 'obj_type': либо 'file', либо 'folder'."""
        collection = None
        if (obj_type is None) or (obj_type != 'file' and obj_type != 'folder'):
            return print(self.top10.__doc__)
        else:
            if obj_type == 'file':
                collection = self.all_files
            elif obj_type == 'folder':
                collection = self.all_folders
            top10 = sorted(collection, key=lambda obj: obj.size, reverse=True)[:10]
            top_10 = []
            for num, i in enumerate(top10, start=1):
                top_10.append(f'{num}. {i}, {self._size(i)}')
        return print(*top_10, sep="\n", end='\n\n')

    def upload(self, object):
        """Метод загруджает на Яндекс.Диск файлы и папки с компьютера, а также фотографии из сети по URL."""

        def _check_folder_exist(folder_name, target_folderpath):
            param = {"path": target_folderpath}
            test = requests.get(self.URL, headers=self.headers, params=param)
            if "/" in target_folderpath:
                if test.status_code == 404:
                    folder = target_folderpath.split("/")
                    print(folder)
                    param = {"path": folder[0]}
                    test = requests.get(self.URL, headers=self.headers, params=param)
                    if test.status_code == 404:
                        folder_name = folder[0]
                        self.create_folder(folder_name, folder)
                        folder_name = folder[-1]
                        self.create_folder(folder_name, target_folderpath)
                    else:
                        self.create_folder(folder_name, target_folderpath)
            else:
                self.create_folder(folder_name, target_folderpath)

        def _upload_folder(folder_path):
            file_list = os.listdir(folder_path)
            message = str
            for file in tqdm(file_list):
                try:
                    param = {"path": f"{folder_path}/{file}"}
                    full_path = os.path.join(folder_path, file)
                    upload_url = requests.get(self.URL + "/upload", headers=self.headers, params=param).json()["href"]
                    with open(full_path, "rb") as _file:
                        requests.put(upload_url, data=_file)
                    message = f"\n======\n\n" \
                              f"Все файлы из папки {folder_name} успешно загружены на Яндекс.Диск\n"
                except KeyError:
                    print(f'Файл "{file}" был ранее загружен на Яндекс.Диск\n')
                    message = (f'\n======\n\n'
                               f'Все файлы из папки {folder_name} загружены на Яндекс.Диск\n')
            return message

        def _upload_file(file, targetpath, fullpath):
            try:
                param = {"path": f"{targetpath}/{file}"}
                print(param)
                print(requests.get(self.URL + "/upload", headers=self.headers, params=param).json())
                upload_url = requests.get(self.URL + "/upload", headers=self.headers, params=param).json()["href"]

                file_size = os.path.getsize(fullpath)
                pbar = tqdm(total=file_size)
                callback = track_upload_progress(pbar)

                e = MultipartEncoder(
                    fields={'file': ('filename', open(fullpath, 'rb'), 'text/plain')}
                    )
                m = MultipartEncoderMonitor(e, callback)

                requests.put(
                    upload_url,
                    data=m,
                    headers={'Content-Type': m.content_type}
                )
                pbar.close()
                print(f'Файл "{file}" успешно загружен на Яндекс.Диск\n')
            except KeyError:
                print(f'Файл "{file}" был ранее загружен на Яндекс.Диск\n')

        def _upload_url(url, likes, date):
            date = str(datetime.fromtimestamp(date).date())
            param = {"path": target_folderpath + "/" + str(likes) + "_" + date + ".jpg", "url": url}
            return requests.post(self.URL + "/upload", headers=self.headers, params=param)

        if len(object) == 2:
            folder = "photos"
            folder_name = object[1]
            target_folderpath = folder + "/" + folder_name
            _check_folder_exist(folder_name, target_folderpath)
            for url, likes, date in tqdm(object[0]):
                _upload_url(url, likes, date)
        else:
            object_full_path = str
            if os.path.exists(os.path.abspath(object)):
                object_full_path = os.path.join('.', object)
            else:
                folder_scan = os.walk(os.path.curdir)
                for root, dirs, files in folder_scan:
                    for dir in dirs:
                        if object == dir:
                            object_full_path = os.path.join(root, dir)
                    else:
                        for file in files:
                            if object == file:
                                object_full_path = os.path.join(root, file)
            object_realpath = object_full_path.split('.\\')[1].replace("\\", "/")
            if os.path.isdir(object_full_path):
                folder_name = object
                target_folderpath = object_realpath
                _check_folder_exist(folder_name, target_folderpath)
                _upload_folder(target_folderpath)
            else:
                if ".zip" in object:
                    name = object.split(".zip")[0]
                    for file in self.all_files:
                        if file.name.split(".")[0] == name:
                            target_folderpath = file.path.split("/" + file.name)[0]
                            _upload_file(object, target_folderpath, object_full_path)
                            return
                    for folder in self.all_folders:
                        if folder.name.split(".")[0] == name:
                            target_folderpath = folder.path.split("/" + folder.name)[0]
                            _upload_file(object, target_folderpath, object_full_path)
                            return
                else:
                    folder_name = object_realpath.split("/" + object)[0]
                    target_folderpath = object_realpath.split("/" + object)[0]
                    _check_folder_exist(folder_name, target_folderpath)
                    _upload_file(object, target_folderpath, object_full_path)

        self.reload()
        self.print_all('file')
        self.print_all('folder')

    @staticmethod
    def zip_file(item):
        """Метод архивирует файл или папку в формат zip."""
        base_path = "downloads"
        full_name = item.name
        object_full_path = str
        folder_scan = os.walk(os.path.join(os.path.curdir, base_path))
        for root, dirs, files in folder_scan:
            for dir in dirs:
                if full_name == dir:
                    object_full_path = os.path.join(root, dir)
            else:
                for file in files:
                    if full_name == file:
                        object_full_path = os.path.join(root, file)
        name = os.path.splitext(full_name)[0]
        path = item.path.split('disk:/')[1]
        with zipfile.ZipFile(os.path.join(base_path, name) + '.zip', "w") as fzip:
            if "." in item.name:
                fzip.write(filename=object_full_path, arcname=full_name)
            else:
                folder = os.walk(os.path.join(base_path, path))
                for root, _dirs, files in folder:
                    dir_name = root.split(base_path)[1]
                    fzip.write(filename=root, arcname=dir_name)
                    for filename in files:
                        fzip.write(filename=os.path.join(root, filename), arcname=os.path.join(dir_name, filename))

        info = {
            "file_name": item.name,
            "size": item.size,
            "path": item.path
        }
        with open(f"{fzip.filename}_info.json", "w") as file:
            json.dump(info, file)
        print(f"{os.path.basename(fzip.filename).capitalize()} успешно создан")
        return os.path.basename(fzip.filename)


class YaFile(YaDisk):
    """Класс создаёт в программе абстракцию сущностей Яндекс.Диска - файлов.
    Экземпляры класса содержат всю полноту информации о сущностях, имеющуюся на Яндекс.Диске."""

    # noinspection Pylint
    def __init__(self, item):
        self.antivirus_status = item['antivirus_status']
        self.size = item['size']
        self.comment_ids = item['comment_ids']
        self.name = item['name']
        self.exif = item['exif']
        self.created = item['created']
        self.resource_id = item['resource_id']
        self.modified = item['modified']
        self.mime_type = item['mime_type']
        self.link = item['file']
        self.path = item['path']
        self.media_type = item['media_type']
        self.sha256 = item['sha256']
        self.md5 = item['md5']
        self.type = item['type']
        self.revision = item['revision']


class YaFolder(YaDisk):
    # noinspection Pylint
    """Класс создаёт в программе абстракцию сущностей Яндекс.Диска - папок.
       Экземпляры класса содержат всю полноту информации о сущностях, имеющуюся на Яндекс.Диске."""

    def __init__(self, item):
        self.name = item['name']
        self.exif = item['exif']
        self.created = item['created']
        self.resource_id = item['resource_id']
        self.modified = item['modified']
        self.comment_ids = item['comment_ids']
        self.path = item['path']
        self.type = item['type']
        self.revision = item['revision']
        self.size = item['size']
