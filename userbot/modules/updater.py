# Copyright (C) 2019 The Raphielscape Company LLC.
# Import from https://github.com/KenHV/KensurBot
#
# Licensed under the Raphielscape Public License, Version 1.c (the "License");
# you may not use this file except in compliance with the License.
# credits to @AvinashReddy3108
#
"""
This module updates the userbot based on upstream revision
"""

import asyncio
import sys
from os import environ, execle, path, remove

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError

from userbot import (
    CMD_HELP,
    HEROKU_API_KEY,
    HEROKU_APP_NAME,
    UPSTREAM_REPO_BRANCH,
    UPSTREAM_REPO_URL,
)
from userbot.events import register

requirements_path = path.join(
    path.dirname(path.dirname(path.dirname(__file__))), "requirements.txt"
)


async def gen_chlog(repo, diff):
    ch_log = ""
    d_form = "%d/%m/%y"
    for c in repo.iter_commits(diff):
        ch_log += (
            f"- {c.summary} ({c.committed_datetime.strftime(d_form)}) <{c.author}>\n"
        )
    return ch_log


async def print_changelogs(event, ac_br, changelog):
    changelog_str = (
        f"**Pembaruan tersedia di {ac_br} branch!\n\nChangelog:**\n`{changelog}`"
    )
    if len(changelog_str) > 4096:
        await event.edit("**Changelog terlalu besar, dikirim sebagai file.**")
        with open("output.txt", "w+") as file:
            file.write(changelog_str)
        await event.client.send_file(event.chat_id, "output.txt")
        remove("output.txt")
    else:
        await event.client.send_message(event.chat_id, changelog_str)
    return True


async def update_requirements():
    reqs = str(requirements_path)
    try:
        process = await asyncio.create_subprocess_shell(
            " ".join([sys.executable, "-m", "pip", "install", "-r", reqs]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        return process.returncode
    except Exception as e:
        return repr(e)


async def deploy(event, repo, ups_rem, ac_br, txt):
    if HEROKU_API_KEY is not None:
        import heroku3

        heroku = heroku3.from_key(HEROKU_API_KEY)
        heroku_app = None
        heroku_applications = heroku.apps()
        if HEROKU_APP_NAME is None:
            await event.edit(
                "**Harap siapkan** `HEROKU_APP_NAME` **variabel"
                " untuk dapat mendeploy userbot Anda.**"
            )
            repo.__del__()
            return
        for app in heroku_applications:
            if app.name == HEROKU_APP_NAME:
                heroku_app = app
                break
        if heroku_app is None:
            await event.edit(
                f"{txt}\n"
                "**Kredensial Heroku tidak valid untuk men-deploy dyno userbot.**"
            )
            return repo.__del__()
        ups_rem.fetch(ac_br)
        repo.git.reset("--hard", "FETCH_HEAD")
        heroku_git_url = heroku_app.git_url.replace(
            "https://", "https://api:" + HEROKU_API_KEY + "@"
        )
        if "heroku" in repo.remotes:
            remote = repo.remote("heroku")
            remote.set_url(heroku_git_url)
        else:
            remote = repo.create_remote("heroku", heroku_git_url)
        try:
            remote.push(refspec="HEAD:refs/heads/master", force=True)
        except Exception as error:
            await event.edit(f"{txt}\nHere is the error log:\n`{error}`")
            return repo.__del__()
        build = app.builds(order_by="created_at", sort="desc")[0]
        if build.status == "failed":
            await event.edit(
                "**Build gagal!**\nDibatalkan atau ada beberapa kesalahan.`"
            )
            await asyncio.sleep(5)
            return await event.delete()
        else:
            await event.edit(
                "**Berhasil diperbarui!**\nProjectDark sedang memulai ulang, akan kembali dalam beberapa detik."
            )
    else:
        await event.edit("**Harap siapkan** `HEROKU_API_KEY` **variabel.**")
    return


async def update(event, repo, ups_rem, ac_br):
    try:
        ups_rem.pull(ac_br)
    except GitCommandError:
        repo.git.reset("--hard", "FETCH_HEAD")
    await update_requirements()
    await event.edit(
        "**Berhasil diperbarui!**\nProjectDark sedang memulai ulang, akan kembali dalam beberapa detik."
    )
    # Spin a new instance of bot
    args = [sys.executable, "-m", "userbot"]
    execle(sys.executable, *args, environ)
    return


@register(outgoing=True, pattern=r"^\.update( now| deploy|$)")
async def upstream(event):
    "For .update command, check if the bot is up to date, update if specified"
    await event.edit("**Memeriksa pembaruan, harap tunggu...**")
    conf = event.pattern_match.group(1).strip()
    off_repo = UPSTREAM_REPO_URL
    force_update = False
    try:
        txt = "**Ups .. Updater tidak dapat melanjutkan karena "
        txt += "beberapa masalah**\n`LOGTRACE:`\n"
        repo = Repo()
    except NoSuchPathError as error:
        await event.edit(f"{txt}\n**Direktori** `{error}` **tidak ditemukan.**")
        return repo.__del__()
    except GitCommandError as error:
        await event.edit(f"{txt}\n**Kegagalan awal!** `{error}`")
        return repo.__del__()
    except InvalidGitRepositoryError as error:
        if conf is None:
            return await event.edit(
                f"**Sayangnya, direktori {error} "
                "tampaknya bukan repositori git.\n"
                "Tapi kamu bisa memperbaikinya dengan memperbarui paksa userbot menggunakan **"
                "`.update now.`"
            )
        repo = Repo.init()
        origin = repo.create_remote("upstream", off_repo)
        origin.fetch()
        force_update = True
        repo.create_head("master", origin.refs.master)
        repo.heads.master.set_tracking_branch(origin.refs.master)
        repo.heads.master.checkout(True)

    ac_br = repo.active_branch.name
    if ac_br != UPSTREAM_REPO_BRANCH:
        await event.edit(
            f"**Sepertinya Anda menggunakan branch kustom Anda sendiri: ({ac_br}). \n"
            "Silakan beralih ke** `master` **branch.**"
        )
        return repo.__del__()
    try:
        repo.create_remote("upstream", off_repo)
    except BaseException:
        pass

    ups_rem = repo.remote("upstream")
    ups_rem.fetch(ac_br)

    changelog = await gen_chlog(repo, f"HEAD..upstream/{ac_br}")
    """ - Special case for deploy - """
    if conf == "deploy":
        await event.edit(
            "**Melakukan pembaruan penuh...**\nIni biasanya membutuhkan waktu kurang dari 5 menit, mohon tunggu."
        )
        await deploy(event, repo, ups_rem, ac_br, txt)
        return

    if changelog == "" and not force_update:
        await event.edit(
            f"**ProjectDark sudah diperbarui dengan `{UPSTREAM_REPO_BRANCH}`!**"
        )
        return repo.__del__()

    if conf == "" and not force_update:
        await print_changelogs(event, ac_br, changelog)
        await event.delete()
        return await event.respond(
            "**Lakukan** `.update now` **atau** `.update deploy` **untuk memperbaharui.**"
        )

    if force_update:
        await event.edit(
            "**Sinkronisasi paksa ke kode userbot stabil terbaru, harap tunggu...**"
        )

    if conf == "now":
        await event.edit("**Melakukan pembaruan cepat, harap tunggu...**")
        await update(event, repo, ups_rem, ac_br)
    return


CMD_HELP.update(
    {
        "update": ">`.update`"
        "\nUsage: Memeriksa apakah repositori userbot utama memiliki pembaruan "
        "dan menunjukkan log perubahan jika demikian."
        "\n\n>`.update now`"
        "\nUsage: Melakukan pembaruan cepat."
        "\n\n>`.update deploy`"
        "\nUsage: Melakukan pembaruan penuh (direkomendasikan)."
    }
)
