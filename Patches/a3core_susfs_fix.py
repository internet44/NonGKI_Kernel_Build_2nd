#!/usr/bin/env python3
# Samsung A03 Core (4.14.199, IverCoder stock): the generic SUSFS 4.14 patch
# rejects four hunks because Samsung's fs/ differs in context. This script
# adds exactly those hunks by hand. Run it from the kernel root after the
# SUSFS patch (with SKIP_PATCH=true so the rejects do not stop the build).
import sys

INTERNAL = '#include "internal.h"\n'


def edit(path, fn):
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        src = f.read()
    out = fn(src)
    if out == src:
        sys.exit(f"[-] {path}: nothing changed")
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(out)
    print(f"[+] {path}: fixed")


def after_internal(block):
    def fn(src):
        if "linux/susfs_def.h" in src:
            return src + ""  # already there -> forces "nothing changed"
        assert INTERNAL in src
        return src.replace(INTERNAL, INTERNAL + block, 1)
    return fn


edit("fs/namespace.c", after_internal(
    "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#endif // #ifdef CONFIG_KSU_SUSFS\n"
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "extern bool susfs_is_current_ksu_domain(void);\n"
    "extern struct static_key_true susfs_is_sdcard_android_data_not_decrypted;\n"
    "#define CL_COPY_MNT_NS BIT(25) /* used by copy_mnt_ns() */\n"
    "#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"))

edit("fs/super.c", after_internal(
    "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#include <linux/jump_label.h>\n#endif // #ifdef CONFIG_KSU_SUSFS\n"
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "extern bool susfs_is_current_ksu_domain(void);\n"
    "extern struct static_key_true susfs_is_sdcard_android_data_not_decrypted;\n"
    "#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"))

edit("fs/namei.c", after_internal(
    "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#endif // #ifdef CONFIG_KSU_SUSFS\n"))

FDINFO_BLOCK = r'''#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
		if (susfs_is_current_app_uid()) {
			bool is_fuse = false;
			if (susfs_is_inode_sus_kstat(inode, &is_fuse)) {
				unsigned long ino = inode->i_ino;
				dev_t dev = inode->i_sb->s_dev;
				susfs_sus_kstat_spoof_inotify_fdinfo(&ino, &dev);
				seq_printf(m, "inotify wd:%x ino:%lx sdev:%x mask:%x ignored_mask:0 ",
						inode_mark->wd, ino, dev, mask);
				show_mark_fhandle(m, inode);
				seq_putc(m, '\n');
				iput(inode);
				return;
			}
		}
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
		if (likely(susfs_is_current_proc_umounted())) {
			struct mount *mnt = real_mount(file->f_path.mnt);
			if (mnt->mnt_id >= DEFAULT_KSU_MNT_ID) {
				struct path path;
				char *pathname = kmalloc(PAGE_SIZE, GFP_KERNEL);
				char *dpath;
				if (!pathname) {
					goto orig_flow;
				}
				dpath = d_path(&file->f_path, pathname, PAGE_SIZE);
				if (!dpath) {
					goto out_kfree;
				}
				if (kern_path(dpath, 0, &path)) {
					goto out_kfree;
				}
				if (!d_backing_inode(path.dentry)) {
					goto out_path_put;
				}
				seq_printf(m, "inotify wd:%x ino:%lx sdev:%x mask:%x ignored_mask:0 ",
						inode_mark->wd, d_backing_inode(path.dentry)->i_ino, d_backing_inode(path.dentry)->i_sb->s_dev,
						mask);
				show_mark_fhandle(m, d_backing_inode(path.dentry));
				seq_putc(m, '\n');
				path_put(&path);
				kfree(pathname);
				iput(inode);
				return;
out_path_put:
				path_put(&path);
out_kfree:
				kfree(pathname);
			}
		}
orig_flow:
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
'''

ANCHOR = "\t\tu32 mask = mark->mask & IN_ALL_EVENTS;\n"


FAN_SIG = "static void fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark)\n"
SUSFS_IF = "#if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_SUS_KSTAT)\n"


def fix_fdinfo(src):
    assert src.count(ANCHOR) == 1, "fdinfo anchor not unique"
    assert "susfs_is_current_proc_umounted()" not in src, "already fixed"
    src = src.replace(ANCHOR, ANCHOR + FDINFO_BLOCK, 1)
    # A03 has CONFIG_FANOTIFY=y: show_fdinfo() takes the 3-arg callback under
    # SUSFS, so fanotify_fdinfo needs the same (unused) file parameter.
    assert src.count(FAN_SIG) == 1, "fanotify_fdinfo signature not found"
    src = src.replace(FAN_SIG,
        SUSFS_IF
        + "static void fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)\n"
        + "#else\n" + FAN_SIG + "#endif\n", 1)
    return src


edit("fs/notify/fdinfo.c", fix_fdinfo)
