import logging
import subprocess
import sys

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render

from .forms import BackupSettingsForm, RestoreForm
from .models import BackupSettings
from .utils import (
    get_backup_info,
    get_snapshot_list,
    is_backup_path_available,
    restore_from_backup,
    sync_to_all_paths,
)

logger = logging.getLogger(__name__)


def backup_settings_view(request):
    """Backup configuration, status, backup list, and restore."""
    settings_obj = BackupSettings.get()

    if request.method == "POST":
        form = BackupSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            logger.info(
                "[Backup] Settings saved (local=%s, external=%s)",
                form.cleaned_data["local_backup_path"],
                form.cleaned_data["external_backup_path"],
            )
            messages.success(request, "Backup settings saved.")
            return redirect("backup:settings")
    else:
        form = BackupSettingsForm(instance=settings_obj)

    restore_form = RestoreForm()

    local_info = None
    external_info = None
    local_available = False
    external_available = False

    if settings_obj.local_backup_path:
        local_available = is_backup_path_available(settings_obj.local_backup_path)
        if local_available:
            local_info = get_backup_info(settings_obj.local_backup_path)

    if settings_obj.external_backup_path:
        external_available = is_backup_path_available(settings_obj.external_backup_path)
        if external_available:
            external_info = get_backup_info(settings_obj.external_backup_path)

    snapshot_list = []
    if local_available and settings_obj.local_backup_path:
        snapshot_list = get_snapshot_list(settings_obj.local_backup_path)

    return render(request, "backup/settings.html", {
        "form": form,
        "restore_form": restore_form,
        "settings_obj": settings_obj,
        "local_available": local_available,
        "external_available": external_available,
        "local_info": local_info,
        "external_info": external_info,
        "snapshot_list": snapshot_list,
    })


def backup_now_view(request):
    """Trigger an immediate sync to all configured paths. POST only."""
    if request.method != "POST":
        return redirect("backup:settings")

    settings_obj = BackupSettings.get()
    if not settings_obj.local_backup_path and not settings_obj.external_backup_path:
        messages.error(request, "No backup paths configured. Please set at least one in Backup Settings.")
        return redirect("backup:settings")

    try:
        result = sync_to_all_paths(reason="manual")
        if "FAILED" in result:
            messages.warning(request, result)
        else:
            messages.success(request, result)
    except Exception as exc:
        logger.exception("[Backup] Manual backup failed")
        messages.error(request, f"Backup failed: {exc}")

    return redirect("backup:settings")


def backup_restore_view(request):
    """Restore from a backup folder or legacy .zip file. POST only."""
    if request.method != "POST":
        return redirect("backup:settings")

    form = RestoreForm(request.POST)
    if not form.is_valid():
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)
        return redirect("backup:settings")

    source = form.cleaned_data["backup_source"]

    try:
        msg = restore_from_backup(source)
        messages.warning(request, msg)
    except Exception as exc:
        logger.exception("[Backup] Restore failed")
        messages.error(request, f"Restore failed: {exc}")

    return redirect("backup:settings")


def api_pick_folder(request):
    """Open the modern Windows folder picker (same style as file picker).

    Uses IFileOpenDialog COM API via PowerShell + inline C#, which gives the
    full modern Vista-style dialog with breadcrumbs, search, sidebar, New Folder.
    """
    if sys.platform != "win32":
        return JsonResponse({"error": "Folder picker is only available on Windows."}, status=400)

    initial = request.GET.get("initial", "").strip()
    return _run_picker(_build_folder_picker_script(initial), "Folder")


def api_pick_file(request):
    """Open the modern Windows file picker dialog filtered to .zip files."""
    if sys.platform != "win32":
        return JsonResponse({"error": "File picker is only available on Windows."}, status=400)

    initial = request.GET.get("initial", "").strip()
    return _run_picker(_build_file_picker_script(initial), "File")


# ---------------------------------------------------------------------------
# PowerShell dialog helpers
# ---------------------------------------------------------------------------

_CSHARP_PICKER = r'''
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
public class FileOpenDialogCls {}

[ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IFileOpenDialog {
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint cFileTypes, IntPtr rgFilterSpec);
    void SetFileTypeIndex(uint iFileType);
    void GetFileTypeIndex(out uint piFileType);
    void Advise(IntPtr pfde, out uint pdwCookie);
    void Unadvise(uint dwCookie);
    void SetOptions(uint fos);
    void GetOptions(out uint pfos);
    void SetDefaultFolder(IShellItem psi);
    void SetFolder(IShellItem psi);
    void GetFolder(out IShellItem ppsi);
    void GetCurrentSelection(out IShellItem ppsi);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string pszName);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
    void GetResult(out IShellItem ppsi);
    void AddPlace(IShellItem psi, int fdap);
    void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string pszDefaultExtension);
    void Close(int hr);
    void SetClientGuid(ref Guid guid);
    void ClearClientData();
    void SetFilter(IntPtr pFilter);
    void GetResults(out IntPtr ppenum);
    void GetSelectedItems(out IntPtr ppsai);
}

[ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem ppsi);
    void GetDisplayName(uint sigdnName, [MarshalAs(UnmanagedType.LPWStr)] out string ppszName);
    void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
    void Compare(IShellItem psi, uint hint, out int piOrder);
}

public static class NativePicker {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    static extern int SHCreateItemFromParsingName(
        [MarshalAs(UnmanagedType.LPWStr)] string pszPath, IntPtr pbc,
        [In] ref Guid riid, [MarshalAs(UnmanagedType.Interface)] out IShellItem ppv);

    public static string PickFolder(string title, string startDir) {
        IFileOpenDialog dlg = (IFileOpenDialog)new FileOpenDialogCls();
        uint opts;
        dlg.GetOptions(out opts);
        dlg.SetOptions(opts | 0x20u);
        if (!string.IsNullOrEmpty(title)) dlg.SetTitle(title);
        SetInitialDir(dlg, startDir);
        if (dlg.Show(IntPtr.Zero) != 0) return "";
        return GetResultPath(dlg);
    }

    public static string PickFile(string title, string startDir) {
        IFileOpenDialog dlg = (IFileOpenDialog)new FileOpenDialogCls();
        if (!string.IsNullOrEmpty(title)) dlg.SetTitle(title);
        SetInitialDir(dlg, startDir);
        if (dlg.Show(IntPtr.Zero) != 0) return "";
        return GetResultPath(dlg);
    }

    static void SetInitialDir(IFileOpenDialog dlg, string dir) {
        if (string.IsNullOrEmpty(dir)) return;
        Guid iid = typeof(IShellItem).GUID;
        IShellItem folder;
        if (SHCreateItemFromParsingName(dir, IntPtr.Zero, ref iid, out folder) == 0)
            dlg.SetFolder(folder);
    }

    static string GetResultPath(IFileOpenDialog dlg) {
        IShellItem item;
        dlg.GetResult(out item);
        string path;
        item.GetDisplayName(0x80058000u, out path);
        return path ?? "";
    }
}
'''


def _build_folder_picker_script(initial_dir=""):
    safe_dir = initial_dir.replace('"', '`"') if initial_dir else ""
    return (
        f'Add-Type -TypeDefinition @"\n{_CSHARP_PICKER}\n"@\n'
        f'Write-Host ([NativePicker]::PickFolder("Select Backup Folder", "{safe_dir}"))'
    )


def _build_file_picker_script(initial_dir=""):
    safe_dir = initial_dir.replace('"', '`"') if initial_dir else ""
    return (
        f'Add-Type -TypeDefinition @"\n{_CSHARP_PICKER}\n"@\n'
        f'Write-Host ([NativePicker]::PickFile("Select Backup File to Restore", "{safe_dir}"))'
    )


def _run_picker(ps_script, label):
    """Execute a PowerShell picker script and return a JSON response."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NoLogo", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        selected = result.stdout.strip()
        if result.returncode != 0 and not selected:
            stderr = result.stderr.strip()
            logger.warning("[Backup] %s picker stderr: %s", label, stderr)
            return JsonResponse({"error": f"Picker failed: {stderr[:200]}"}, status=500)
        if selected:
            return JsonResponse({"path": selected})
        return JsonResponse({"path": "", "cancelled": True})
    except subprocess.TimeoutExpired:
        return JsonResponse({"error": f"{label} picker timed out."}, status=408)
    except Exception as exc:
        logger.warning("[Backup] %s picker failed: %s", label, exc)
        return JsonResponse({"error": f"Could not open {label.lower()} picker: {exc}"}, status=500)
