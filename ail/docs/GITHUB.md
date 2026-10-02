# Подготовленный репозиторий AIL

Имя репозитория, которое можно использовать: **ail**. Подготовленная версия:
**0.1.1**, ветка `main`, лицензия MIT. Репозиторий пока не опубликован.

## Содержимое комплекта

- `ail/` — исходники, install/uninstall, примеры, документация и `.github`.
- `ail.bundle` — git-история подготовленного проекта для локального клонирования.
- `release/` — готовый tar.gz, wheel, sdist и контрольные суммы для релиза.

ZIP сам по себе не импортируется GitHub как дерево исходников: сначала распакуй
его, затем используй git push либо веб-загрузку отдельных файлов. Для сохранения
истории и прав исполнения удобнее клонировать bundle.

## Вариант 1: GitHub CLI и готовая история

Из каталога распакованного комплекта клонируй bundle в новое место:

```bash
git clone ail.bundle ail-repo
cd ail-repo
git remote remove origin
gh auth login
gh repo create ail --private --source=. --remote=origin --push
```

Команда создаёт приватный репозиторий в аккаунте, выбранном в `gh auth login`.
Для публичного используй `--public` вместо `--private`. Если нужен репозиторий
организации, укажи `ORGANIZATION/ail` вместо `ail`. Перед будущими коммитами
настрой свои `git user.name` и `git user.email`.

В подготовленном bundle первый коммит имеет технического автора
`AIL Development <ail@localhost>`. Это не адрес для связи и не твоя учётная запись.
При необходимости перед первым push можно переоформить авторство коммита:

```bash
git commit --amend --reset-author --no-edit
```

Эту команду используй после настройки собственных name/email; она меняет hash
коммита. Bundle содержит ветку main, без готового тега, поэтому тег новой истории
можно создать после проверки.

## Вариант 2: обычный git

Создай на GitHub пустой репозиторий без автоматически добавленных README/LICENSE,
затем в локальном клоне bundle:

```bash
git remote remove origin
git remote add origin git@github.com:YOUR_ACCOUNT/ail.git
git push -u origin main
```

`origin` сразу после клонирования bundle указывает на локальный файл.
Замени `YOUR_ACCOUNT` своим аккаунтом или организацией. Для HTTPS можно использовать
`https://github.com/YOUR_ACCOUNT/ail.git`. Токены не вставляй в URL и исходники.

Если работаешь с папкой `ail/` из ZIP без bundle, перед push создай историю:

```bash
cd ail
git init -b main
git add .
git commit -m "Add AIL compiler, installer and CI"
```

Затем добавь remote и выполни push. Настрой свою git identity до коммита.

## CI

После push ветки main и при pull requests workflow `CI` проверяет:

- тесты компилятора и установщика на Python 3.10, 3.12 и 3.13;
- согласованность сгенерированных примеров и JSON Schema;
- сборку wheel/sdist;
- установку wheel в отдельный venv и нативный Hello World вне checkout.

Workflow использует Ubuntu 24.04 x86-64. Непосредственно GitHub Actions ещё не
запускался: этот комплект подготовлен локально. Локально пройдены тесты на
Python 3.12.14, установка/удаление, сборка пакетов и запуск из wheel.

## Релиз

После успешного CI и выбора коммита:

```bash
git tag v0.1.1
git push origin v0.1.1
```

Workflow `Release artifacts` проверяет соответствие тега версии проекта,
запускает тесты и создаёт скачиваемый artifact `ail-distributions`.
В него входят tar.gz с установщиком, контрольная сумма, wheel и sdist.
Релиз GitHub и публикация PyPI автоматически не создаются.

Для первого релиза можно сразу прикрепить файлы из папки `release/` комплекта
в интерфейсе GitHub Releases. Если переоформил коммит или изменил исходники,
собери актуальные артефакты заново:

```bash
python3 tools/build_release.py
python3 -m pip install build
python3 -m build
```

Сборщик tar.gz использует чистые tracked files текущего checkout. Готовый бинарник
в tar.gz — только пример Hello World, сам компилятор поставляется как Python-код.
