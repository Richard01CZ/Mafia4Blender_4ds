from datetime import datetime
import os
import bpy # type: ignore
import bmesh # type: ignore
import struct
import re
import math
import array
from mathutils import Quaternion, Matrix, Vector # type: ignore
from bpy_extras.io_utils import ImportHelper, ExportHelper # type: ignore
from bpy.props import StringProperty, EnumProperty, IntProperty, FloatProperty, FloatVectorProperty, BoolProperty, CollectionProperty # type: ignore
from bpy.types import AddonPreferences # type: ignore
bl_info = {
    "name": "LS3D 4DS Importer/Exporter",
    "author": "Richard01_CZ, Sev3n", # Special thanks to: Asa, Oravin, kirill_mapper, FlashX, sadness_smile, huckleberrypie
    "version": (0, 6, 0, 'privateTest' ),
    "blender": (5, 1, 0),
    "location": "File > Import/Export > 4DS Model File",
    "description": "Import and export LS3D .4ds model files (Mafia)",
    "category": "Import-Export",
}
# FileVersion consts
VERSION_MAFIA = 29
VERSION_HD2 = 41
VERSION_CHAMELEON = 42

# Frame Types
FRAME_VISUAL = 1        # 3D Object                 COMPLETE
FRAME_LIGHT = 2         # Possibly HD2?             UNSUPPORTED
FRAME_CAMERA = 3        # Possibly HD2?             UNSUPPORTED
FRAME_SOUND = 4         # Possibly HD2?             UNSUPPORTED  
FRAME_SECTOR = 5        # 3D Object Wireframe       COMPLETE                    Make it so sector deosn't require flipping normals (currently sector requires to have it's faces facing inside)
FRAME_DUMMY = 6         # Empty (Cube)              COMPLETE                    Dummies are mostlikely displayed incorrectly for vehicles
FRAME_TARGET = 7        # Empty (Plain Axis)        COMPLETE
FRAME_USER = 8          # HD2                       UNSUPPORTED
FRAME_MODEL = 9         # Empty (Arrows)            UNSUPPORTED
FRAME_JOINT = 10        # Armature/Bones            COMPLETE
FRAME_VOLUME = 11       # HD2                       UNSUPPORTED
FRAME_OCCLUDER = 12     # 3D Object Wireframe       COMPLETE                    Occluder isn't correctly parsed/imported by Mafcapone (not sure), software update may be required to fix this. Occluders in seperate blender collection are recommended
FRAME_SCENE = 13        # HD2                       UNSUPPORTED
FRAME_AREA = 14         # HD2                       UNSUPPORTED
FRAME_LANDSCAPE = 15    # HD2                       UNSUPPORTED

# Add an option to show or hide the raw int values in 4ds side panels
# Map vehicle dummies and create N panel with all dummy types for a specific thing of the vehicle.

# Visual Types
VISUAL_OBJECT = 0           # COMPLETE ?
VISUAL_LITOBJECT = 1        # UNSUPPORTED
VISUAL_SINGLEMESH = 2       # COMPLETE
VISUAL_SINGLEMORPH = 3      # COMPLETE
VISUAL_BILLBOARD = 4        # COMPLETE
VISUAL_MORPH = 5            # COMPLETE
VISUAL_LENSFLARE = 6        # COMPLETE
VISUAL_PROJECTOR = 7        # UNSUPPORTED
VISUAL_MIRROR = 8           # COMPLETE
VISUAL_EMITOR = 9           # UNSUPPORTED

# ==============================================================================
# BLEND BONE HELPERS
# ==============================================================================
def _is_blend_bone(bone, armature_obj=None):
    """True if *bone* is the blend bone (mesh-frame bone) for the armature.

    In the 4DS format every root bone is a child of the SINGLEMESH visual
    frame, and ``parent_joint_id == 0`` in the skin data refers to that
    frame.  During import we create a bone for it so weighted vertices
    that blend with identity (the mesh frame) are handled correctly by
    Blender's armature modifier.  This bone is NOT a FRAME_JOINT and
    must be excluded from export paths that write joint data.

    Determined solely by the ``ls3d_is_blend_bone`` custom property."""
    if armature_obj is not None:
        pb = armature_obj.pose.bones.get(bone.name) if hasattr(bone, 'name') else None
        return bool(pb and pb.get("ls3d_is_blend_bone"))
    # Also support being called on a pose bone directly
    if hasattr(bone, 'get'):
        return bool(bone.get("ls3d_is_blend_bone"))
    return False

# ==============================================================================
# RESULT POPUP DIALOGS
# ==============================================================================
# Shared storage for the scrollable error/success dialog.
_log_title    = ""
_log_icon     = 'INFO'


# ── Logging ──────────────────────────────────────────────────────────────────
# The LS3D Log popup shows error/warning counts and suggested fixes.
# Full details are printed to the Blender system console.

_log_errors = 0
_log_warns  = 0
_log_fixes  = []   # list of suggested fix strings


class LS3D_OT_ResultPopup(bpy.types.Operator):
    """LS3D Log summary popup."""
    bl_idname  = "ls3d.result_popup"
    bl_label   = "LS3D Log"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        layout = self.layout
        layout.label(text=_log_title, icon=_log_icon)
        layout.separator()

        if _log_errors > 0:
            layout.label(text=f"{_log_errors} error(s)", icon='CANCEL')
        if _log_warns > 0:
            layout.label(text=f"{_log_warns} warning(s)", icon='ERROR')
        if _log_errors == 0 and _log_warns == 0:
            layout.label(text="No issues found.", icon='CHECKMARK')

        # Show suggested fixes
        if _log_fixes:
            layout.separator()
            layout.label(text="Suggested fixes:", icon='TOOL_SETTINGS')
            box = layout.box()
            for fix in _log_fixes:
                box.label(text=fix)

        if _log_errors > 0 or _log_warns > 0:
            layout.separator()
            layout.label(text="Open Blender console for full details:", icon='INFO')
            layout.label(text="   Window > Toggle System Console")


def _show_log():
    """Invoke the popup operator."""
    bpy.ops.ls3d.result_popup('INVOKE_DEFAULT')


def _add_fix(text):
    """Add a suggested fix (shown in the popup)."""
    if text not in _log_fixes:
        _log_fixes.append(text)


def log_clear(title, icon='INFO'):
    """Start a fresh log for an import/export operation."""
    global _log_title, _log_icon, _log_errors, _log_warns
    _log_title = title
    _log_icon  = icon
    _log_errors = 0
    _log_warns  = 0
    _log_fixes.clear()
    print(f"\n{'='*60}")
    print(f"[LS3D] {title}")
    print(f"{'='*60}")


def _set_log_title(title):
    """Update the popup title (e.g. to reflect success/failure)."""
    global _log_title
    _log_title = title


def log_info(text):
    """Print an info line to the console."""
    print(f"[LS3D] {text}")


def log_warn(text):
    """Print a warning to the console and increment the warning count."""
    global _log_warns, _log_icon
    _log_warns += 1
    print(f"[LS3D] WARNING: {text}")
    if _log_icon not in ('CANCEL',):
        _log_icon = 'ERROR'


def log_error(text):
    """Print an error to the console and increment the error count."""
    global _log_errors, _log_icon
    _log_errors += 1
    print(f"[LS3D] ERROR: {text}")
    _log_icon = 'CANCEL'


def log_success(text):
    """Print a success message to the console."""
    global _log_icon
    print(f"[LS3D] {text}")
    if _log_icon == 'INFO':
        _log_icon = 'CHECKMARK'


def log_separator():
    """Print a blank line to the console."""
    print()


# ==============================================================================
# VIEWPORT DISPLAY COLORS (hex → linear RGBA)
# ==============================================================================
def _hex(h):
    r = ((h >> 16) & 0xFF) / 255.0
    g = ((h >> 8)  & 0xFF) / 255.0
    b = (  h       & 0xFF) / 255.0
    return (r, g, b, 1.0)

# Frame type colors
COLOR_FRAME_VISUAL      = _hex(0xFFFFFF)
COLOR_FRAME_SECTOR      = _hex(0x00FFFF)
COLOR_FRAME_PORTAL      = _hex(0x9926FF)
COLOR_FRAME_OCCLUDER    = _hex(0xFFAA00)
COLOR_FRAME_DUMMY       = _hex(0x0000FF)
COLOR_FRAME_TARGET      = _hex(0x00FF00)
COLOR_FRAME_JOINT       = _hex(0x00B6FF)

# Visual sub-type colors (only used when frame type is FRAME_VISUAL)
COLOR_VISUAL_OBJECT      = _hex(0xFFFFFF)
COLOR_VISUAL_LITOBJECT   = _hex(0xFF0000) # Should never appear, original intended color 0xAAAAFF
COLOR_VISUAL_SINGLEMESH  = _hex(0xFFB6B2)
COLOR_VISUAL_SINGLEMORPH = _hex(0xFFA2E8)
COLOR_VISUAL_BILLBOARD   = _hex(0x00B600)
COLOR_VISUAL_MORPH       = _hex(0xFF00FF)
COLOR_VISUAL_LENSFLARE   = _hex(0xFFFFAA)
COLOR_VISUAL_MIRROR      = _hex(0x7FFF7F)

# # Material Flags (Full 32-bit map)
# MTL_MISC_UNLIT              = 0x00000001 # 
# MTL_ENV_OVERLAY             = 0x00000100 # 
# MTL_ENV_MULTIPLY            = 0x00000200 # 
# MTL_ENV_ADDITIVE            = 0x00000400 # 
# MTL_ENVTEX                  = 0x00000800 # UNKNOWN? Why do i have this
# MTL_ALPHA_ENABLE            = 0x00008000 # 
# MTL_DISABLE_U_TILING        = 0x00010000 # 
# MTL_DISABLE_V_TILING        = 0x00020000 # 
# MTL_DIFFUSE_ENABLE          = 0x00040000 # 
# MTL_ENV_ENABLE              = 0x00080000 # 
# MTL_ENV_PROJY               = 0x00001000 # 
# MTL_ENV_DETAILY             = 0x00002000 # 
# MTL_ENV_DETAILZ             = 0x00004000 # 
# MTL_UNKNOWN_20              = 0x00100000 # 
# MTL_UNKNOWN_21              = 0x00200000 # 
# MTL_UNKNOWN_22              = 0x00400000 # 
# MTL_DIFFUSE_MIPMAP          = 0x00800000 # 
# MTL_ALPHA_IN_TEX            = 0x01000000 # 
# MTL_ALPHA_ANIMATED          = 0x02000000 # 
# MTL_DIFFUSE_ANIMATED        = 0x04000000 # 
# MTL_DIFFUSE_COLORED         = 0x08000000 # 
# MTL_DIFFUSE_DOUBLESIDED     = 0x10000000 # 
# MTL_ALPHA_COLORKEY          = 0x20000000 # 
# MTL_ALPHATEX                = 0x40000000 # 
# MTL_ALPHA_ADDITIVE          = 0x80000000 # 

# Material Flags (Full 32-bit map)
MTL_MISC_UNLIT              = 1 << 0
MTL_ENV_OVERLAY             = 1 << 8
MTL_ENV_MULTIPLY            = 1 << 9
MTL_ENV_ADDITIVE            = 1 << 10
MTL_ENVTEX                  = 1 << 11 # UNKNOWN? Why do i have this
MTL_ENV_PROJY               = 1 << 12
MTL_ENV_DETAILY             = 1 << 13
MTL_ENV_DETAILZ             = 1 << 14
MTL_ALPHA_ENABLE            = 1 << 15
MTL_DISABLE_U_TILING        = 1 << 16
MTL_DISABLE_V_TILING        = 1 << 17
MTL_DIFFUSE_ENABLE          = 1 << 18
MTL_ENV_ENABLE              = 1 << 19
MTL_UNKNOWN_20              = 1 << 20
MTL_UNKNOWN_21              = 1 << 21
MTL_UNKNOWN_22              = 1 << 22
MTL_DIFFUSE_MIPMAP          = 1 << 23
MTL_ALPHA_IN_TEX            = 1 << 24
MTL_ALPHA_ANIMATED          = 1 << 25
MTL_DIFFUSE_ANIMATED        = 1 << 26
MTL_DIFFUSE_COLORED         = 1 << 27
MTL_DIFFUSE_DOUBLESIDED     = 1 << 28
MTL_ALPHA_COLORKEY          = 1 << 29
MTL_ALPHATEX                = 1 << 30
MTL_ALPHA_ADDITIVE          = 1 << 31


# --- VISUAL RENDER FLAGS (Byte 1) ---      MOSTLIKELY UNUSED
RF_UNKNOWN1         = 0x01  # 1
RF_UNKNOWN2         = 0x02  # 2
RF_UNKNOWN3         = 0x04  # 4
RF_UNKNOWN4         = 0x08  # 8
RF_UNKNOWN5         = 0x10  # 16
RF_UNKNOWN6         = 0x20  # 32
RF_HIDEMESH         = 0x40  # 64 / Makes the object mesh invisible, animated mesh gets teleported to XYZ 0 0 0
RF_NOSHADING         = 0x80  # 128 / Disables Shading of the object

# --- VISUAL LOGIC FLAGS (Byte 2) ---
LF_ZBIAS                            = 0x01  # 1 Object acts a decal (Poster, picture on a wall). helps with z-fighting on flat surfaces by drawing the object above the surface.
LF_RECIEVE_DYNAMIC_SHADOW_DIFFUSE   = 0x02  # 2 Object can recieve dynamic shadows on diffuse material (eg. from player or vehicle)
LF_RECIEVE_DYNAMIC_SHADOW_ALPHA     = 0x04  # 4 Object can recieve dynamic shadows on alpha (transparent) material (eg. from player or vehicle)                                 # Thanks h0ns4!
LF_MIRRORABLE                       = 0x08  # 8 Object is visible in mirrors
LF_UNKNOWN5                         = 0x10  # 16 Used for equipment (bagpacks, hats, weapons)                                                                                   [Description may apply to HD2 only]
LF_RECIEVE_PROJECTION_DIFFUSE       = 0x20  # 32 Object can recieve projection textures on diffuse materials (eg. Car headlights, bullet hole decals)
LF_RECIEVE_PROJECTION_ALPHA         = 0x40  # 64 Object can recieve projection textures on alpha (transparent) materials (eg. Car headlights, bullet hole decals)               # Thanks h0ns4!
LF_NO_FOG                           = 0x80  # 128 Object isn't affected by the scene fog

# --- NODE CULLING FLAGS ---
CF_ENABLED          = 0x01  # 1 Enables/Makes object visible
CF_UNKNOWN2         = 0x02  # 2
CF_UNKNOWN3         = 0x04  # 4
CF_CAST_SHADOW      = 0x08  # 8 Objects Casts shadows on itself
CF_UNKNOWN5         = 0x10  # 16
CF_UNKNOWN6         = 0x20  # 32
CF_HIERARCHY        = 0x40  # 64 Simple Sector? Object is a parent and has children, if disabled children aren't detected
CF_UNKNOWN8         = 0x80  # 128

# --- SECTOR FLAGS ---
SF_ENABLED          = 0x00000001 # Sector is enabled
SF_UNKNOWN7         = 0x00000400
SF_UNKNOWN8         = 0x00000800 # Indoor? Sets the Sector to act as an interior?

# --- PORTAL FLAGS ---
PF_UNKNOWN1             = 0x00000001
PF_UNKNOWN2             = 0x00000002
PF_ENABLED              = 0x00000004 # Enables rendering of the portal
PF_UNKNOWN4             = 0x00000008 # Makes the portal a mirror?


class LS3D_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    textures_path: StringProperty(name="Path to Textures", description='Path to the textures "maps" folder. This path is used by the importer.', subtype='DIR_PATH', default="") # type: ignore

    fix_multi_influences: BoolProperty(
        name="More than 2 Bone Influences",
        description="On export, automatically reduce vertices with more than 2 bone influences "
                    "by removing the weakest and redistributing their weight",
        default=False,
    ) # type: ignore

    fix_non_parent_child: BoolProperty(
        name="Non-Parent-Child Weights",
        description="On export, automatically correct vertices weighted to two bones "
                    "that are not a direct parent-child pair",
        default=False,
    ) # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.label(text="LS3D Configuration", icon='SETTINGS')
        layout.prop(self, "textures_path")
        layout.separator()
        layout.label(text="Export Weight Corrections", icon='MOD_VERTEX_WEIGHT')
        layout.prop(self, "fix_multi_influences")
        layout.prop(self, "fix_non_parent_child")

# ── Property Groups ───────────────────────────────────────────────

class LS3DMorphTarget(bpy.types.PropertyGroup):
    shape_key_name: StringProperty() # type: ignore
    select:         BoolProperty(default=False) # type: ignore

class LS3DMorphGroup(bpy.types.PropertyGroup):
    name:                StringProperty(default="Group") # type: ignore
    targets:             CollectionProperty(type=LS3DMorphTarget) # type: ignore
    active_target_index: IntProperty(default=0, update=lambda self, ctx: _on_active_target(self, ctx)) # type: ignore


# ── Helpers ───────────────────────────────────────────────────────

def _on_active_target(group, context):
    obj = context.object
    if not obj or not obj.data:
        return
    sk = obj.data.shape_keys
    if not sk:
        return
    tidx = group.active_target_index
    if 0 <= tidx < len(group.targets):
        i = sk.key_blocks.find(group.targets[tidx].shape_key_name)
        if i >= 0:
            obj.active_shape_key_index = i

def _mg(obj):
    i = getattr(obj, 'ls3d_active_morph_group', -1)
    if obj and 0 <= i < len(obj.ls3d_morph_groups):
        g = obj.ls3d_morph_groups[i]
        return g, g.active_target_index
    return None, -1


# ── UI Lists ──────────────────────────────────────────────────────

class LS3D_UL_MorphGroups(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.prop(item, "name", text="", emboss=False, icon='GROUP_VERTEX')

class LS3D_UL_MorphTargets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        obj = context.object
        sk  = obj.data.shape_keys if obj and obj.data else None
        key = sk.key_blocks.get(item.shape_key_name) if sk else None

        if not key:
            layout.label(text=item.shape_key_name or "(none)", icon='ERROR')
            return

        layout.label(text=key.name, icon='SHAPEKEY_DATA')

        r = layout.row(align=True)
        r.alignment = 'RIGHT'
        if index == 0:
            r.label(text="Basis")   # index 0 in THIS group is the basis — not sk.reference_key
        else:
            v = r.row()
            v.scale_x = 0.55
            v.prop(key, "value", text="", emboss=False)
            op = r.operator("ls3d.morph_select_toggle", text="",
                            icon='CHECKBOX_HLT' if item.select else 'CHECKBOX_DEHLT',
                            emboss=False)
            op.index = index


# ── Operators ─────────────────────────────────────────────────────

class LS3D_OT_MorphSelectToggle(bpy.types.Operator):
    bl_idname  = "ls3d.morph_select_toggle"
    bl_label   = "Toggle Selection"
    bl_options = {'INTERNAL'}
    index: IntProperty(options={'HIDDEN'}) # type: ignore

    def execute(self, context):
        g, _ = _mg(context.object)
        if g and 0 <= self.index < len(g.targets):
            g.targets[self.index].select = not g.targets[self.index].select
        return {'FINISHED'}


class LS3D_OT_MorphGroup(bpy.types.Operator):
    """Add or remove a morph group"""
    bl_idname  = "ls3d.morph_group"
    bl_label   = "Morph Group"
    bl_options = {'REGISTER', 'UNDO'}
    action: EnumProperty(items=[('ADD','Add',''),('REMOVE','Remove','')], options={'HIDDEN'}) # type: ignore

    def execute(self, context):
        obj = context.object
        if self.action == 'ADD':
            g = obj.ls3d_morph_groups.add()
            g.name = f"Group {len(obj.ls3d_morph_groups)}"
            obj.ls3d_active_morph_group = len(obj.ls3d_morph_groups) - 1
        else:
            i = obj.ls3d_active_morph_group
            if 0 <= i < len(obj.ls3d_morph_groups):
                obj.ls3d_morph_groups.remove(i)
                obj.ls3d_active_morph_group = max(0, i - 1)
        return {'FINISHED'}


class LS3D_OT_MorphTarget(bpy.types.Operator):
    """Add, remove, or move shape keys in the active morph group"""
    bl_idname  = "ls3d.morph_target"
    bl_label   = "Morph Target"
    bl_options = {'REGISTER', 'UNDO'}
    action:   EnumProperty(items=[('ADD','Add',''),('REMOVE','Remove',''),
                                   ('UP','Up',''),('DOWN','Down','')],
                            options={'HIDDEN'}) # type: ignore
    from_mix: BoolProperty(default=False, options={'HIDDEN'}) # type: ignore

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH' and context.object.mode != 'EDIT'

    def execute(self, context):
        obj = context.object
        sk  = obj.data.shape_keys if obj.data else None
        g, tidx = _mg(obj)
        if g is None:
            return {'CANCELLED'}

        hid = obj.hide_viewport
        obj.hide_viewport = True

        if self.action == 'ADD':
            # Redirect to the existing shape key picker
            obj.hide_viewport = hid
            return bpy.ops.ls3d.morph_add_existing('INVOKE_DEFAULT')

        elif self.action == 'REMOVE':
            # Remove from group only — do NOT delete the shape key itself
            to_rm = [t.shape_key_name for t in g.targets if t.select] or \
                    ([g.targets[tidx].shape_key_name] if 0 <= tidx < len(g.targets) else [])
            for name in to_rm:
                i = next((i for i, t in enumerate(g.targets) if t.shape_key_name == name), -1)
                if i >= 0:
                    g.targets.remove(i)
            g.active_target_index = max(0, min(g.active_target_index, len(g.targets) - 1))

        elif self.action in ('UP', 'DOWN') and sk:
            if self.action == 'UP' and tidx > 0:
                obj.active_shape_key_index = sk.key_blocks.find(g.targets[tidx].shape_key_name)
                bpy.ops.object.shape_key_move(type='UP')
                g.targets.move(tidx, tidx - 1)
                g.active_target_index = tidx - 1
            elif self.action == 'DOWN' and tidx < len(g.targets) - 1:
                obj.active_shape_key_index = sk.key_blocks.find(g.targets[tidx].shape_key_name)
                bpy.ops.object.shape_key_move(type='DOWN')
                g.targets.move(tidx, tidx + 1)
                g.active_target_index = tidx + 1

        obj.hide_viewport = hid
        return {'FINISHED'}

class LS3D_OT_MorphAddExisting(bpy.types.Operator):
    """Add an existing shape key to the active morph group"""
    bl_idname  = "ls3d.morph_add_existing"
    bl_label   = "Add Existing Shape Key"
    bl_options = {'REGISTER', 'UNDO'}

    shape_key_name: StringProperty(name="Shape Key", default="") # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'MESH' or obj.mode == 'EDIT':
            return False
        g, _ = _mg(obj)
        return g is not None

    def get_items(self, context):
        obj = context.object
        sk  = obj.data.shape_keys if obj and obj.data else None
        if not sk:
            return [('', '(none)', '')]
        g, _ = _mg(obj)
        already = {t.shape_key_name for t in g.targets} if g else set()
        items = [(kb.name, kb.name, '') for kb in sk.key_blocks if kb.name not in already]
        return items if items else [('', '(none available)', '')]

    def invoke(self, context, event):
        items = self.get_items(context)
        if not items or items[0][0] == '':
            self.report({'WARNING'}, "No unassigned shape keys available.")
            return {'CANCELLED'}
        # Default to first available
        self.shape_key_name = items[0][0]
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        items = self.get_items(context)
        # Build enum dynamically in the dialog
        self.layout.label(text="Select shape key to add:")
        col = self.layout.column(align=True)
        obj = context.object
        sk  = obj.data.shape_keys if obj and obj.data else None
        if not sk:
            return
        g, _ = _mg(obj)
        already = {t.shape_key_name for t in g.targets} if g else set()
        for kb in sk.key_blocks:
            if kb.name in already:
                continue
            row = col.row()
            row.enabled = True
            op = row.operator("ls3d.morph_add_existing_pick", text=kb.name,
                              icon='SHAPEKEY_DATA' if kb.name != sk.reference_key.name else 'KEY_HLT')
            op.shape_key_name = kb.name

    def execute(self, context):
        obj = context.object
        sk  = obj.data.shape_keys if obj and obj.data else None
        g, _ = _mg(obj)
        if not g or not sk:
            return {'CANCELLED'}
        if not self.shape_key_name or self.shape_key_name not in sk.key_blocks:
            self.report({'WARNING'}, f"Shape key '{self.shape_key_name}' not found.")
            return {'CANCELLED'}
        already = {t.shape_key_name for t in g.targets}
        if self.shape_key_name in already:
            self.report({'WARNING'}, f"'{self.shape_key_name}' is already in this group.")
            return {'CANCELLED'}
        t = g.targets.add()
        t.shape_key_name = self.shape_key_name
        g.active_target_index = len(g.targets) - 1
        return {'FINISHED'}


class LS3D_OT_MorphAddExistingPick(bpy.types.Operator):
    """Add this shape key to the morph group"""
    bl_idname  = "ls3d.morph_add_existing_pick"
    bl_label   = "Pick Shape Key"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    shape_key_name: StringProperty(options={'HIDDEN'}) # type: ignore

    def execute(self, context):
        obj = context.object
        sk  = obj.data.shape_keys if obj and obj.data else None
        g, _ = _mg(obj)
        if not g or not sk:
            return {'CANCELLED'}
        already = {t.shape_key_name for t in g.targets}
        if self.shape_key_name in already:
            self.report({'WARNING'}, f"'{self.shape_key_name}' is already in this group.")
            return {'CANCELLED'}
        if self.shape_key_name not in sk.key_blocks:
            return {'CANCELLED'}
        t = g.targets.add()
        t.shape_key_name = self.shape_key_name
        g.active_target_index = len(g.targets) - 1
        return {'FINISHED'}

class LS3D_OT_MorphTransfer(bpy.types.Operator):
    """For each other selected object: copies its active morph target onto this object.
    Select the source morph on the other object, shift-select this object to make it active, then press Transfer."""
    bl_idname  = "ls3d.morph_transfer"
    bl_label   = "Transfer Morph"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (obj and obj.type == 'MESH' and obj.mode != 'EDIT'
                and len(context.selected_objects) > 1)

    def execute(self, context):

        obj = context.object
        sk  = obj.data.shape_keys
        g, _ = _mg(obj)
        if g is None:
            self.report({'ERROR'}, "No active morph group on target object")
            return {'CANCELLED'}

        if not obj.data.vertices:
            self.report({'ERROR'}, "Target object has no geometry")
            return {'CANCELLED'}

        # Ensure target object has at least a Basis morph
        if not sk:
            obj.shape_key_add(name="Basis", from_mix=False)
            sk = obj.data.shape_keys
            t = g.targets.add()
            t.shape_key_name = "Basis"

        imported = 0
        failures = []  # collect (object_name, reason) for final report

        for src_obj in context.selected_objects:
            if src_obj is obj or src_obj.type != 'MESH':
                continue

            if not src_obj.data.vertices:
                failures.append((src_obj.name, "has no geometry"))
                continue

            src_sk = src_obj.data.shape_keys
            if not src_sk:
                failures.append((src_obj.name, "has no morph targets"))
                continue

            src_key = src_obj.active_shape_key
            if not src_key:
                failures.append((src_obj.name, "no active morph target selected"))
                continue

            if src_key == src_sk.reference_key:
                failures.append((src_obj.name, "cannot transfer the Basis morph"))
                continue

            if len(src_key.data) != len(obj.data.vertices):
                failures.append((src_obj.name,
                    f"vertex count mismatch ({len(src_key.data)} on source vs "
                    f"{len(obj.data.vertices)} on target) — transfer requires identical mesh topology"))
                continue

            # Check for corrupted morph data (NaN / Inf coords)
            bad_verts = [
                i for i in range(len(src_key.data))
                if not all(math.isfinite(c) for c in src_key.data[i].co)
            ]
            if bad_verts:
                failures.append((src_obj.name,
                    f"morph '{src_key.name}' has {len(bad_verts)} vertex/vertices with "
                    f"NaN or infinite coordinates"))
                continue

            # Copy morph target
            new_key = obj.shape_key_add(name=src_key.name, from_mix=False)
            for i in range(len(new_key.data)):
                new_key.data[i].co = src_key.data[i].co.copy()
            new_key.value         = src_key.value
            new_key.interpolation = src_key.interpolation

            # Sanity check: transferred positions should sit within a reasonable
            # distance of the target mesh's bounding box — if not, the meshes
            # likely have different topology despite matching vertex count
            bbox_min = Vector(obj.bound_box[0])
            bbox_max = Vector(obj.bound_box[6])
            margin   = (bbox_max - bbox_min).length * 2.0
            center   = (bbox_min + bbox_max) * 0.5
            if any((new_key.data[i].co - center).length > margin + 1.0
                   for i in range(len(new_key.data))):
                obj.shape_key_remove(new_key)
                failures.append((src_obj.name,
                    "morph positions land outside target mesh bounds — "
                    "meshes likely have different topology despite matching vertex count"))
                continue

            entry = g.targets.add()
            entry.shape_key_name = new_key.name
            imported += 1

        if imported and not failures:
            g.active_target_index = len(g.targets) - 1
            _on_active_target(g, context)
            self.report({'INFO'}, f"Transferred {imported} morph(s)")
        elif imported and failures:
            g.active_target_index = len(g.targets) - 1
            _on_active_target(g, context)
            reasons = "; ".join(f"{n}: {r}" for n, r in failures)
            self.report({'WARNING'}, f"Transferred {imported} morph(s), {len(failures)} skipped — {reasons}")
        else:
            reasons = "; ".join(f"{n}: {r}" for n, r in failures)
            self.report({'ERROR'}, f"Nothing transferred — {reasons}")

        return {'FINISHED'}

class LS3D_OT_MorphMakeBasis(bpy.types.Operator):
    """Apply the active target as the group basis (same as Blender's Apply as Basis)"""
    bl_idname  = "ls3d.morph_make_basis"
    bl_label   = "Apply as Basis"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or not obj.data:
            return False
        sk = obj.data.shape_keys
        if not sk:
            return False
        g, tidx = _mg(obj)
        return g is not None and tidx > 0

    def execute(self, context):
        obj = context.object
        sk  = obj.data.shape_keys
        g, tidx = _mg(obj)

        key = sk.key_blocks.get(g.targets[tidx].shape_key_name)
        ref = sk.reference_key
        if not key or not ref:
            return {'CANCELLED'}

        n = len(ref.data)

        # Delta: how the key displaces each vertex from the current basis
        delta = [key.data[i].co - ref.data[i].co for i in range(n)]

        # Shift ALL keys except the active key by +delta
        # This includes ref — it moves to key's absolute position
        for kb in sk.key_blocks:
            if kb is key:
                continue
            for i in range(n):
                kb.data[i].co = kb.data[i].co + delta[i]

        # Reset active key to match new basis (zero displacement)
        for i in range(n):
            key.data[i].co = ref.data[i].co.copy()

        # Reorder only our group's target list — never touch key_blocks order
        g.targets.move(tidx, 0)
        g.active_target_index = 0

        obj.data.update()
        return {'FINISHED'}

# ── Panel ─────────────────────────────────────────────────────────

class The4DSPanelMorph(bpy.types.Panel):
    bl_label       = "4DS Morph Groups"
    bl_idname      = "DATA_PT_4ds_morph"
    bl_space_type  = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context     = "data"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'MESH' and getattr(obj, 'visual_type', '') in ('3', '5')

    def draw(self, context):
        layout = self.layout
        obj    = context.object
        sk     = obj.data.shape_keys if obj.data else None

        row = layout.row()
        row.template_list("LS3D_UL_MorphGroups", "",
                          obj, "ls3d_morph_groups",
                          obj, "ls3d_active_morph_group", rows=3)
        c = row.column(align=True)
        c.operator("ls3d.morph_group", icon='ADD',    text="").action = 'ADD'
        c.operator("ls3d.morph_group", icon='REMOVE', text="").action = 'REMOVE'

        g, tidx = _mg(obj)
        if g is None:
            return

        sel = sum(1 for t in g.targets if t.select)
        hr  = layout.row()
        hr.label(text=f'"{g.name}" targets:')
        if sel:
            hr.label(text=f"{sel} selected", icon='CHECKBOX_HLT')

        row2 = layout.row()
        row2.template_list("LS3D_UL_MorphTargets", "",
                           g, "targets", g, "active_target_index", rows=5)
        c2 = row2.column(align=True)
        c2.operator("ls3d.morph_target",       icon='ADD',       text="").action = 'ADD'
        c2.operator("ls3d.morph_target",       icon='REMOVE',    text="").action = 'REMOVE'
        c2.separator()
        c2.operator("ls3d.morph_target",       icon='TRIA_UP',   text="").action = 'UP'
        c2.operator("ls3d.morph_target",       icon='TRIA_DOWN', text="").action = 'DOWN'
        c2.separator()
        c2.operator("ls3d.morph_transfer",     icon='COPY_ID',   text="")
        c2.operator("ls3d.morph_make_basis",   icon='CHECKMARK', text="")

        if not sk:
            return

        # Always force relative shape keys
        if not sk.use_relative:
            sk.use_relative = True

        can_edit = obj.mode != 'EDIT'

        key = sk.key_blocks.get(g.targets[tidx].shape_key_name) if 0 <= tidx < len(g.targets) else None
        if not key or key == sk.reference_key or tidx == 0:
            return

        vr = layout.row(); vr.active = can_edit; vr.prop(key, "value")

class LS3DTargetObject(bpy.types.PropertyGroup):
    # Human-readable display name (bone name or object name)
    name:          bpy.props.StringProperty(name="Name") # type: ignore
    # Legacy string path — kept for backward compat on load, prefer pointers below
    target_path:   bpy.props.StringProperty(name="Path") # type: ignore
    # Direct object pointer (for non-bone targets)
    target_object: bpy.props.PointerProperty(name="Object", type=bpy.types.Object) # type: ignore
    # For bone targets: pointer to the armature + bone name string
    target_armature: bpy.props.PointerProperty(name="Armature", type=bpy.types.Object) # type: ignore
    bone_name:       bpy.props.StringProperty(name="Bone", default="") # type: ignore


# Free helper — rebuilds Track To constraints from the collection
def _resolve_target_entry(entry):
    """Return (linked_obj_or_None, pose_bone_or_None) for a target entry."""
    if entry.target_armature and entry.bone_name:
        pb = entry.target_armature.pose.bones.get(entry.bone_name)
        return (None, pb)
    if entry.target_object:
        return (entry.target_object, None)
    # Legacy fallback: try target_path string
    path = entry.target_path
    if path.startswith("BONE:"):
        parts = path.split(":", 2)
        if len(parts) == 3:
            arm_obj = bpy.data.objects.get(parts[1])
            if arm_obj:
                return (None, arm_obj.pose.bones.get(parts[2]))
    else:
        return (bpy.data.objects.get(path), None)
    return (None, None)


def sync_track_to_constraints(target_obj):
    """
    Each object/bone in target_obj's link list gets a Track To constraint
    pointing AT target_obj.
    """
    # First, remove any existing LS3D track constraints from all linked objects
    for entry in target_obj.ls3d_target_objects:
        linked, pose_bone = _resolve_target_entry(entry)
        if pose_bone:
            for c in list(pose_bone.constraints):
                if c.type == 'TRACK_TO' and c.name.startswith("LS3D_Track_"):
                    pose_bone.constraints.remove(c)
        elif linked:
            for c in list(linked.constraints):
                if c.type == 'TRACK_TO' and c.name.startswith("LS3D_Track_"):
                    linked.constraints.remove(c)

    # Now add fresh constraints pointing at the target
    for entry in target_obj.ls3d_target_objects:
        linked, pose_bone = _resolve_target_entry(entry)
        if pose_bone:
            c            = pose_bone.constraints.new('TRACK_TO')
            c.name       = f"LS3D_Track_{target_obj.name}"
            c.target     = target_obj
            c.track_axis = 'TRACK_Y'
            c.up_axis    = 'UP_Z'
        elif linked:
            c            = linked.constraints.new('TRACK_TO')
            c.name       = f"LS3D_Track_{target_obj.name}"
            c.target     = target_obj
            c.track_axis = 'TRACK_Y'
            c.up_axis    = 'UP_Z'


class LS3D_OT_AddTargetObject(bpy.types.Operator):
    bl_idname = "ls3d.add_target_object"
    bl_label  = "Add"

    def execute(self, context):
        obj   = context.object
        raw   = obj.ls3d_target_add_name.strip()

        if not raw:
            self.report({'WARNING'}, "Enter an object name or 'armature:bone'")
            return {'CANCELLED'}

        # Determine target and display name
        if ":" in raw:
            # Bone syntax:  "armature_name:bone_name"
            arm_name, bone_name = raw.split(":", 1)
            arm_obj = bpy.data.objects.get(arm_name)
            if not arm_obj or arm_obj.type != 'ARMATURE':
                self.report({'ERROR'}, f"Armature '{arm_name}' not found")
                return {'CANCELLED'}
            if bone_name not in arm_obj.data.bones:
                self.report({'ERROR'}, f"Bone '{bone_name}' not found in '{arm_name}'")
                return {'CANCELLED'}
            display = bone_name
            # Prevent duplicates
            for entry in obj.ls3d_target_objects:
                if entry.target_armature == arm_obj and entry.bone_name == bone_name:
                    self.report({'WARNING'}, f"'{display}' is already in the list")
                    return {'CANCELLED'}
            entry                  = obj.ls3d_target_objects.add()
            entry.name             = display
            entry.target_armature  = arm_obj
            entry.bone_name        = bone_name
            entry.target_path      = f"BONE:{arm_name}:{bone_name}"
        else:
            # Plain object
            target = bpy.data.objects.get(raw)
            if not target:
                self.report({'ERROR'}, f"Object '{raw}' not found")
                return {'CANCELLED'}
            if target == obj:
                self.report({'WARNING'}, "Cannot target self")
                return {'CANCELLED'}
            display = raw
            # Prevent duplicates
            for entry in obj.ls3d_target_objects:
                if entry.target_object == target:
                    self.report({'WARNING'}, f"'{display}' is already in the list")
                    return {'CANCELLED'}
            entry                = obj.ls3d_target_objects.add()
            entry.name           = display
            entry.target_object  = target
            entry.target_path    = raw
        obj.ls3d_target_objects_index = len(obj.ls3d_target_objects) - 1
        obj.ls3d_target_add_name = ""

        sync_track_to_constraints(obj)
        return {'FINISHED'}


class LS3D_OT_RemoveTargetObject(bpy.types.Operator):
    bl_idname = "ls3d.remove_target_object"
    bl_label  = "Remove"

    def execute(self, context):
        obj = context.object
        idx = obj.ls3d_target_objects_index
        if not (0 <= idx < len(obj.ls3d_target_objects)):
            return {'CANCELLED'}

        entry = obj.ls3d_target_objects[idx]

        # Remove the constraint from the linked object/bone before deleting the entry
        constraint_name = f"LS3D_Track_{obj.name}"
        linked, pose_bone = _resolve_target_entry(entry)
        if pose_bone:
            for c in list(pose_bone.constraints):
                if c.type == 'TRACK_TO' and c.name == constraint_name:
                    pose_bone.constraints.remove(c)
        elif linked:
            for c in list(linked.constraints):
                if c.type == 'TRACK_TO' and c.name == constraint_name:
                    linked.constraints.remove(c)

        obj.ls3d_target_objects.remove(idx)
        obj.ls3d_target_objects_index = max(0, idx - 1)
        return {'FINISHED'}

class The4DSPanel(bpy.types.Panel):
    bl_label = "4DS Object Properties"
    bl_idname = "OBJECT_PT_4ds"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    # ==========================================================
    # EXPOSURE MAPS
    # ==========================================================

    VISUAL_EXPOSURE = {
        VISUAL_OBJECT: [
            "render",
            "logic",
            "cull",
            "lod",
            "user",
        ],
        VISUAL_MIRROR: [
            "mirror",
            "render",
            "logic",
            "cull",
            "user",
        ],
        VISUAL_BILLBOARD: [
            "billboard",
            "render",
            "logic",
            "cull",
            "lod",
            "user",
        ],
        VISUAL_LENSFLARE: [
            "lensflare",
            "render",
            "logic",
            "cull",
            "user",
        ],
        VISUAL_SINGLEMESH: [
            "render",
            "logic",
            "cull",
            "lod",
            "user",
        ],
        VISUAL_SINGLEMORPH: [
            "render",
            "logic",
            "cull",
            "lod",
            "user",
        ],
        VISUAL_MORPH: [
            "render",
            "logic",
            "cull",
            "lod",
            "user",
        ],
    }

    FRAME_EXPOSURE = {
        FRAME_SECTOR: [
            "sector",
            "cull",
            "user",
        ],
        FRAME_DUMMY: [
            "cull",
            "user",
        ],
        FRAME_OCCLUDER: [
            "occluder",
            "cull",
            "user",
        ],
        FRAME_TARGET: [
            "target",
            "cull",
            "user",
        ],
    }

    # ==========================================================
    # PORTAL DETECTION
    # ==========================================================

    def is_portal(self, obj):
        try:
            frame_type = int(obj.ls3d_frame_type)
        except:
            return False

        if frame_type != FRAME_SECTOR:
            return False

        if obj.type != 'MESH':
            return False

        if not obj.parent:
            return False

        try:
            parent_type = int(obj.parent.ls3d_frame_type)
        except:
            return False

        if parent_type != FRAME_SECTOR:
            return False

        return re.search(r"_portal\d+$", obj.name, re.IGNORECASE) is not None

    # ==========================================================
    # DRAW BLOCKS
    # ==========================================================

    def draw_render(self, layout, obj):
        box = layout.box()
        box.label(text="Rendering Flags", icon='RESTRICT_RENDER_OFF')
        box.prop(obj, "render_flags", text="Raw Int")
        grid = box.grid_flow(columns=2, align=True)
        grid.prop(obj, "rf1_unknown1", toggle=True)
        grid.prop(obj, "rf1_unknown2", toggle=True)
        grid.prop(obj, "rf1_unknown3", toggle=True)
        grid.prop(obj, "rf1_unknown4", toggle=True)
        grid.prop(obj, "rf1_unknown5", toggle=True)
        grid.prop(obj, "rf1_unknown6", toggle=True)
        grid.prop(obj, "rf1_hidemesh", toggle=True)
        grid.prop(obj, "rf1_noshading", toggle=True)

    def draw_logic(self, layout, obj):
        box = layout.box()
        box.label(text="Logic Flags", icon='MODIFIER')
        box.prop(obj, "render_flags2", text="Raw Int")
        grid = box.grid_flow(columns=2,    align=True)
        grid.prop(obj, "rf2_zbias",                             toggle=True)
        grid.prop(obj, "rf2_recieve_dynamic_shadow_diffuse",    toggle=True)
        grid.prop(obj, "rf2_recieve_dynamic_shadow_alpha",      toggle=True)
        grid.prop(obj, "rf2_mirrorable",                        toggle=True)
        grid.prop(obj, "rf2_unknown5",                          toggle=True)
        grid.prop(obj, "rf2_recieve_projection_diffuse",        toggle=True)
        grid.prop(obj, "rf2_recieve_projection_alpha",          toggle=True)
        grid.prop(obj, "rf2_no_fog",                            toggle=True)

    def draw_cull(self, layout, obj):
        box = layout.box()
        box.label(text="Node Culling Flags", icon='PROPERTIES')
        box.prop(obj, "cull_flags", text="Raw Int")
        grid = box.grid_flow(columns=2, align=True)
        grid.prop(obj, "cf_enabled",     toggle=True)
        grid.prop(obj, "cf_unknown2",    toggle=True)
        grid.prop(obj, "cf_unknown3",    toggle=True)
        grid.prop(obj, "cf_cast_shadow", toggle=True)
        grid.prop(obj, "cf_unknown5",    toggle=True)
        grid.prop(obj, "cf_unknown6",    toggle=True)
        grid.prop(obj, "cf_hierarchy",   toggle=True)
        grid.prop(obj, "cf_unknown8",    toggle=True)

    def draw_mirror(self, layout, obj):
        box = layout.box()
        box.label(text="Mirror Settings", icon='MOD_MIRROR')
        box.prop(obj, "ls3d_mirror_color", text="Color")
        box.prop(obj, "ls3d_mirror_range", text="Active Range")

    def draw_billboard(self, layout, obj):
        box = layout.box()
        box.label(text="Billboard Settings", icon='IMAGE_PLANE')
        box.prop(obj, "rot_mode", text="Rotation Mode")
        if obj.rot_mode == '2':
            box.prop(obj, "rot_axis", text="Rotation Axis")

    def draw_lensflare(self, layout, obj):
        box = layout.box()
        box.label(text="Lens Flare", icon='LIGHT')
        box.prop(obj, "ls3d_glow_position", text="Screen Position")
        box.prop(obj, "ls3d_glow_material", text="Material")

    def draw_lod(self, layout, obj):
        box = layout.box()
        box.label(text="Level Of Detail", icon='MESH_DATA')
        box.prop(obj, "ls3d_lod_dist", text="Fade Distance")

    def draw_sector(self, layout, obj):
        box = layout.box()
        box.label(text="Sector Flags", icon='SCENE_DATA')
        box.prop(obj, "ls3d_sector_flags1_str", text="Raw Flags 1 (Hex)")
        box.prop(obj, "ls3d_sector_flags2_str", text="Raw Flags 2 (Hex)")
        grid = box.grid_flow(columns=2, align=True)
        grid.prop(obj, "sf_enabled",  toggle=True)
        grid.prop(obj, "sf_unknown7", toggle=True)
        grid.prop(obj, "sf_unknown8", toggle=True)

    def draw_portal(self, layout, obj):
        box = layout.box()
        box.label(text="Portal Settings", icon='OUTLINER_OB_LIGHT')
        box.prop(obj, "ls3d_portal_flags", text="Raw Flags")
        row = box.row(align=True)
        row.prop(obj, "ls3d_portal_near", text="Near")
        row.prop(obj, "ls3d_portal_far",  text="Far")
        grid = box.grid_flow(columns=2, align=True)
        grid.prop(obj, "pf_unknown1", toggle=True)
        grid.prop(obj, "pf_unknown2", toggle=True)
        grid.prop(obj, "pf_enabled",  toggle=True)
        grid.prop(obj, "pf_unknown4",   toggle=True)

    def draw_occluder(self, layout, obj):
        box = layout.box()
        box.label(text="Occluder", icon='MOD_BOOLEAN')
        box.label(text="No editable properties")

    def draw_user(self, layout, obj):
        box = layout.box()
        box.prop(obj, "ls3d_user_props", text="User Props", icon='TEXT')

    def draw_target(self, layout, obj):
        box = layout.box()
        box.label(text="Target Settings", icon='EMPTY_ARROWS')
        box.prop(obj, "ls3d_target_flags", text="Flags")
        box.separator()
        box.label(text="Targeted Objects:")
        row = box.row()
        row.template_list("UI_UL_list", "ls3d_target_objects", obj, "ls3d_target_objects", obj, "ls3d_target_objects_index", rows=4)
        row.operator("ls3d.remove_target_object", icon='REMOVE', text="")
        row2 = box.row(align=True)
        row2.prop(obj, "ls3d_target_add_name", text="")
        row2.operator("ls3d.add_target_object", icon='ADD', text="Add")
        box.label(text="Use 'armature:bone' syntax for bones", icon='INFO')

    def draw_joint(self, layout, bone):
        # ── Blend Bone Toggle ─────────────────────────────────────────────────
        is_blend = bool(bone.get("ls3d_is_blend_bone"))
        box_blend = layout.box()
        row_blend = box_blend.row(align=True)
        row_blend.label(text="Blend Bone", icon='BONE_DATA')
        if is_blend:
            row_blend.operator("ls3d.set_blend_bone", text="Blend Bone ✓", icon='CHECKMARK', depress=True)
        else:
            row_blend.operator("ls3d.set_blend_bone", text="Set as Blend", icon='RADIOBUT_OFF')
        if is_blend:
            box_blend.label(text="This bone is the blend bone (mesh frame).", icon='INFO')
            # Blend bone has no joint properties — skip the rest
            return

        # ── Joint Scale ───────────────────────────────────────────────────────
        if "ls3d_joint_scale" not in bone:
            bone["ls3d_joint_scale"] = (1.0, 1.0, 1.0)
        box = layout.box()
        box.label(text="Joint Scale", icon='FULLSCREEN_ENTER')
        row = box.row(align=True)
        row.prop(bone, '["ls3d_joint_scale"]', index=0, text="X")
        row.prop(bone, '["ls3d_joint_scale"]', index=1, text="Y")
        row.prop(bone, '["ls3d_joint_scale"]', index=2, text="Z")

        # ── Culling Flags ─────────────────────────────────────────────────────
        box2 = layout.box()
        box2.label(text="Node Culling Flags", icon='PROPERTIES')
        box2.prop(bone, "cull_flags", text="Raw Flags")
        grid = box2.grid_flow(columns=2, align=True)
        grid.prop(bone, "cf_enabled",     toggle=True)
        grid.prop(bone, "cf_unknown2",    toggle=True)
        grid.prop(bone, "cf_unknown3",    toggle=True)
        grid.prop(bone, "cf_cast_shadow", toggle=True)
        grid.prop(bone, "cf_unknown5",    toggle=True)
        grid.prop(bone, "cf_unknown6",    toggle=True)
        grid.prop(bone, "cf_hierarchy",   toggle=True)
        grid.prop(bone, "cf_unknown8",    toggle=True)

        # ── User Properties ───────────────────────────────────────────────────
        box3 = layout.box()
        box3.prop(bone, "user_props", text="User Props", icon='TEXT')

    # ==========================================================
    # MAIN DRAW
    # ==========================================================

    def draw(self, context):
        layout = self.layout

        obj = context.object
        if not obj:
            return

        # -------------------------------------------------------
        # ARMATURE in Pose Mode — context.active_pose_bone is None
        # in bl_context="object", read bone from armature directly
        # -------------------------------------------------------
        if obj.type == 'ARMATURE' and obj.mode == 'POSE':
            active_bone = obj.data.bones.active
            bone = obj.pose.bones.get(active_bone.name) if active_bone else None
            if bone:
                layout.label(text=f"Joint: {bone.name}", icon='BONE_DATA')
                self.draw_joint(layout, bone)
            else:
                box = layout.box()
                box.label(text="No bone selected.", icon='INFO')
                box.label(text="Select a bone in the viewport.")
            return

        # -------------------------------------------------------
        # ARMATURE in Object Mode
        # -------------------------------------------------------
        if obj.type == 'ARMATURE':
            box = layout.box()
            box.label(text="This object contains Joints.", icon='BONE_DATA')
            box.label(text="Enter Pose Mode and select a bone")
            box.label(text="to edit its 4DS properties.")
            layout.separator()
            box.label(text="To Scale the Joint")
            box.label(text="use the custom 4ds scale property!")
            return

        box = layout.box()
        box.label(text="Model Settings", icon='SCENE_DATA')
        box.prop(context.scene, "ls3d_animated_object_count")

        layout.separator()
        layout.prop(obj, "ls3d_frame_type", text="Frame Type")

        try:
            frame_type = int(obj.ls3d_frame_type)
        except:
            return

        exposure = []

        if frame_type == FRAME_VISUAL:
            layout.prop(obj, "visual_type", text="Visual Type")
            try:
                visual_type = int(obj.visual_type)
            except:
                visual_type = 0
            exposure = self.VISUAL_EXPOSURE.get(visual_type, [])

        elif frame_type == FRAME_SECTOR:
            if self.is_portal(obj):
                exposure = ["portal", "cull", "user"]
            else:
                exposure = self.FRAME_EXPOSURE.get(frame_type, [])

        else:
            exposure = self.FRAME_EXPOSURE.get(frame_type, [])

        for block in exposure:
            if   block == "mirror":    self.draw_mirror(layout, obj)
            elif block == "billboard": self.draw_billboard(layout, obj)
            elif block == "lensflare": self.draw_lensflare(layout, obj)
            elif block == "render":    self.draw_render(layout, obj)
            elif block == "logic":     self.draw_logic(layout, obj)
            elif block == "lod":       self.draw_lod(layout, obj)
            elif block == "sector":    self.draw_sector(layout, obj)
            elif block == "portal":    self.draw_portal(layout, obj)
            elif block == "occluder":  self.draw_occluder(layout, obj)
            elif block == "cull":      self.draw_cull(layout, obj)
            elif block == "user":      self.draw_user(layout, obj)
            elif block == "target":    self.draw_target(layout, obj)

class LS3D_OT_SetBlendBone(bpy.types.Operator):
    bl_idname      = "ls3d.set_blend_bone"
    bl_label       = "Set as Blend Bone"
    bl_description = (
        "Toggle the selected bone as the blend bone.  Only one blend bone "
        "is allowed per armature — setting a new one clears the old one.  "
        "The blend bone cannot be a child of any other bone"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE' and obj.mode == 'POSE'
                and context.active_pose_bone is not None)

    def execute(self, context):
        arm_obj = context.active_object
        pbone   = context.active_pose_bone

        # ── Guard: blend bone must be parentless ─────────────────────────
        if pbone.bone.parent is not None:
            self.report({'ERROR'}, f"'{pbone.name}' is a child bone — only root-level bones can be the blend bone.")
            return {'CANCELLED'}

        # ── Guard: blend bone must have no children ──────────────────────
        if pbone.bone.children:
            self.report({'ERROR'}, f"'{pbone.name}' has child bones — the blend bone cannot have any children.")
            return {'CANCELLED'}

        already_blend = bool(pbone.get("ls3d_is_blend_bone"))

        # ── Clear ALL existing blend bone markers on this armature ───────
        for pb in arm_obj.pose.bones:
            if pb.get("ls3d_is_blend_bone"):
                del pb["ls3d_is_blend_bone"]

        # ── Toggle: if this bone was already the blend, just clear it ────
        if already_blend:
            self.report({'INFO'}, f"'{pbone.name}' is no longer the blend bone.")
        else:
            pbone["ls3d_is_blend_bone"] = True
            self.report({'INFO'}, f"'{pbone.name}' is now the blend bone.")

        return {'FINISHED'}


class LS3D_OT_CreateMaterial(bpy.types.Operator):
    bl_idname      = "ls3d.create_material"
    bl_label       = "Create LS3D Material"
    bl_description = "Creates a new material with default LS3D settings and assigns it to the active object"

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No active object selected.")
            return {'CANCELLED'}

        mat = bpy.data.materials.new(name="LS3D_Material")
        mat.ls3d_material_flags = 0
        mat.ls3d_diffuse_color  = (1.0, 1.0, 1.0)
        mat.ls3d_ambient_color  = (0.5, 0.5, 0.5)
        mat.ls3d_emission_color = (0.0, 0.0, 0.0)
        mat.ls3d_opacity        = 1.0
        mat.ls3d_env_amount     = 0.0

        ls3d_rebuild_material_nodes(mat)

        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

        self.report({'INFO'}, f"Created material '{mat.name}'.")
        return {'FINISHED'}
    
class The4DSPanelMaterial(bpy.types.Panel):
    bl_label       = "4DS Material Properties"
    bl_idname      = "MATERIAL_PT_4ds"
    bl_space_type  = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context     = "material"

    def draw(self, context):
        mat = context.material
        obj = context.object
        layout = self.layout

        # ── Material selector ─────────────────────────────────────────────────
        if obj:
            row = layout.row()
            row.template_list("MATERIAL_UL_matslots", "", obj, "material_slots",
                              obj, "active_material_index", rows=3)
            col = row.column(align=True)
            col.operator("object.material_slot_add",    icon='ADD',    text="")
            col.operator("object.material_slot_remove", icon='REMOVE', text="")
            layout.template_ID(obj, "active_material", new="material.new")

        layout.separator()
        layout.operator("ls3d.create_material", icon='MATERIAL', text="Create LS3D Material")

        if not mat:
            return

        layout.separator()

        # ── Colors ────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Colors & Opacity", icon='COLOR')
        col = box.column(align=True)
        col.prop(mat, "ls3d_diffuse_color")
        col.prop(mat, "ls3d_ambient_color")
        col.prop(mat, "ls3d_emission_color")
        col.separator()
        col.prop(mat, "ls3d_opacity", slider=True)

        # ── Global Flags ──────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Global Material Flags", icon='PREFERENCES')
        box.prop(mat, "ls3d_material_flags_str", text="Raw Hex")

        # ── Texture Animation ─────────────────────────────────────────────────
        if mat.ls3d_flag_diffuse_animated or mat.ls3d_flag_alpha_animated:
            box = layout.box()
            box.label(text="Texture Animation", icon='ANIM')
            col = box.column(align=True)
            col.prop(mat, "ls3d_anim_frames")
            col.prop(mat, "ls3d_anim_period")

        # ── Diffuse ───────────────────────────────────────────────────────────
        box = layout.box()
        header = box.row()
        header.label(text="Diffuse & General", icon='TEXTURE')
        header.prop(mat, "ls3d_flag_diffuse_enable", toggle=True,
                    icon='CHECKBOX_HLT' if mat.ls3d_flag_diffuse_enable else 'CHECKBOX_DEHLT')
        col = box.column(align=True)
        grid = col.column(align=True)
        row = grid.row(align=True)
        row.prop(mat, "ls3d_flag_misc_unlit",          toggle=True)
        row.prop(mat, "ls3d_flag_diffuse_doublesided",  toggle=True)
        row = grid.row(align=True)
        row.prop(mat, "ls3d_flag_diffuse_colored",     toggle=True)
        row.prop(mat, "ls3d_flag_diffuse_mipmap",      toggle=True)
        row = grid.row(align=True)
        row.prop(mat, "ls3d_flag_disable_u_tiling",    toggle=True)
        row.prop(mat, "ls3d_flag_disable_v_tiling",    toggle=True)
        row = grid.row(align=True)
        row.prop(mat, "ls3d_flag_diffuse_animated",    toggle=True)
        col.separator()
        col.label(text="Diffuse Texture:")
        col.template_ID(mat, "ls3d_diffuse_tex", open="image.open")

        # ── Alpha ─────────────────────────────────────────────────────────────
        box = layout.box()
        header = box.row()
        header.label(text="Alpha / Transparency", icon='GHOST_ENABLED')
        header.prop(mat, "ls3d_flag_alpha_enable", toggle=True,
                    icon='CHECKBOX_HLT' if mat.ls3d_flag_alpha_enable else 'CHECKBOX_DEHLT')
        col = box.column(align=True)
        grid = col.column(align=True)
        row = grid.row(align=True)
        row.prop(mat, "ls3d_flag_alphatex",        toggle=True)
        row.prop(mat, "ls3d_flag_alpha_in_tex",    toggle=True)
        row = grid.row(align=True)
        row.prop(mat, "ls3d_flag_alpha_colorkey",  toggle=True)
        row.prop(mat, "ls3d_flag_alpha_additive",  toggle=True)
        row = grid.row(align=True)
        row.prop(mat, "ls3d_flag_alpha_animated",  toggle=True)
        col.separator()
        col.label(text="Alpha Texture:")
        col.template_ID(mat, "ls3d_alpha_tex", open="image.open")

        # ── Environment ───────────────────────────────────────────────────────
        box = layout.box()
        header = box.row()
        header.label(text="Environment Mapping", icon='WORLD_DATA')
        header.prop(mat, "ls3d_flag_env_enable", toggle=True,
                    icon='CHECKBOX_HLT' if mat.ls3d_flag_env_enable else 'CHECKBOX_DEHLT')
        col = box.column(align=True)
        col.label(text="Blend Mode:")
        grid = col.column(align=True)
        row = grid.row(align=True)
        row.prop(mat, "ls3d_flag_env_overlay",  toggle=True)
        row.prop(mat, "ls3d_flag_env_multiply",  toggle=True)
        row.prop(mat, "ls3d_flag_env_additive",  toggle=True)
        col.separator()
        col.label(text="Projection / Detail:")
        row = col.row(align=True)
        row.prop(mat, "ls3d_flag_env_projy",    toggle=True)
        row.prop(mat, "ls3d_flag_env_detaily",   toggle=True)
        row.prop(mat, "ls3d_flag_env_detailz",   toggle=True)
        col.separator()
        col.prop(mat, "ls3d_env_amount", slider=True)
        col.separator()
        col.label(text="Environment Texture:")
        col.template_ID(mat, "ls3d_env_tex", open="image.open")

def safe_link(tree, from_socket, to_socket):
    if from_socket and to_socket:
        tree.links.new(from_socket, to_socket)

def _find_node(nodes, label):
    return next((n for n in nodes if n.label == label), None)

def _srgb_to_linear(c):
    if c <= 0.04045:
        return c / 12.92
    else:
        return ((c + 0.055) / 1.055) ** 2.4

class The4DSExporter:
    def __init__(self, filepath, objects, operator, progress_fn=None):
        self.filepath = filepath
        self.objects_to_export = objects
        self.operator = operator
        self._progress_fn = progress_fn  # callback(percent: int)
        self.materials = []
        self.objects = []
        self.version = VERSION_MAFIA
        self.frames_map = {}
        self.joint_maps = {}  # armature_obj → {bone_name: 1-based index}
        self.frame_index = 1
        self.lod_map = {}
        self.errors = []  # collected validation errors

    def progress(self, percent):
        """Update export progress (0-100)."""
        if self._progress_fn:
            self._progress_fn(percent)

    def add_error(self, msg):
        """Record a validation error. Call raise_if_errors() after validation."""
        self.errors.append(msg)
        log_error(msg)

    def raise_if_errors(self):
        """If any errors were collected, raise. Caller handles the popup."""
        if self.errors:
            log_separator()
            log_error(f"Export aborted — {len(self.errors)} error(s)")
            raise RuntimeError("4DS export validation failed")

    def write_string(self, f, text):
        if not text:
            f.write(struct.pack("<B", 0))
            return 0

        encoded = text.encode("windows-1250", errors="replace")
        length = min(len(encoded), 255)

        f.write(struct.pack("<B", length))
        if length > 0:
            f.write(encoded[:length])

        return length


    def serialize_header(self, f):
        f.write(b"4DS\0")
        f.write(struct.pack("<H", self.version))
        now = datetime.now()
        epoch = datetime(1601, 1, 1)
        delta = now - epoch
        filetime = int(delta.total_seconds() * 1e7)
        f.write(struct.pack("<Q", filetime))

    # def collect_materials(self): #FUNTODO
    #     materials = set()
    #     for obj in self.objects_to_export:
    #         if obj.type == 'MESH':
    #             for slot in obj.material_slots:
    #                 if slot.material:
    #                     materials.add(slot.material)
    #     return list(materials)

    def collect_materials(self):
        # Use a dictionary to map Name -> Material to prevent duplicates by name
        # (Blender allows unique materials with same names in libraries, but for 4DS we care about the unique datablock)
        materials_set = set()

        # ---------------------------------------------------------
        # 1. GLOBAL SCAN ("Reserved Slots")
        # ---------------------------------------------------------
        # Look at every material in the Blender file.
        # If it is named "4ds_material_X", we MUST export it to preserve the ID slot,
        # even if no object currently uses it.
        for mat in bpy.data.materials:
            if re.match(r"4ds_material_\d+$", mat.name):
                materials_set.add(mat)

        # ---------------------------------------------------------
        # 2. LOCAL SCAN ("Active Materials")
        # ---------------------------------------------------------
        # Look at the objects we are actually exporting.
        # If they use "Brick_Wall", "Glass", etc., add those too.
        for obj in self.objects_to_export:
            
            # A. Mesh Materials (Slots)
            if obj.type == 'MESH':
                for slot in obj.material_slots:
                    if slot.material:
                        materials_set.add(slot.material)

            # B. Lens Flare Materials (Custom Prop)
            # (Lens flares don't use slots, they use a custom pointer)
            mat = getattr(obj, "ls3d_glow_material", None)
            if mat:
                materials_set.add(mat)

        # ---------------------------------------------------------
        # 3. SORTING STRATEGY
        # ---------------------------------------------------------
        mat_list = list(materials_set)

        def sort_key(mat):
            # Try to match "4ds_material_<number>"
            match = re.match(r"4ds_material_(\d+)$", mat.name)
            
            if match:
                # Group 0: Reserved IDs. Sort by the number.
                # Example: 4ds_material_2 comes before 4ds_material_10
                return (0, int(match.group(1)), "")
            else:
                # Group 1: Custom Names. Sort alphabetically.
                # Example: "Alpha" comes before "Zebra"
                # These will always appear AFTER the highest 4ds_material_X
                return (1, 0, mat.name)

        mat_list.sort(key=sort_key)

        # Debug: Print the final ID mapping to console
        print(f"[4DS Export] Final Material Table:")
        for i, m in enumerate(mat_list):
            print(f"  ID {i+1}: {m.name}")

        return mat_list

    
    def find_texture_node(self, node):
        """Recursively find an Image Texture node."""
        if not node:
            return None
            
        # Case A: It is an Image Node
        if node.type == 'TEX_IMAGE':
            return node
            
        # Case B: It is a Node Group (Dig inside)
        if node.type == 'GROUP' and node.node_tree:
            # Look for the specific texture node inside the group
            # We prioritize nodes labeled "Env Texture" or just the first image node found
            for inner_node in node.node_tree.nodes:
                if inner_node.type == 'TEX_IMAGE':
                    return inner_node
        
        # Case C: Pass-through nodes (Mix, Math, etc)
        if hasattr(node, "inputs"):
            for input_socket in node.inputs:
                if input_socket.is_linked:
                    found = self.find_texture_node(input_socket.links[0].from_node)
                    if found:
                        return found
        return None
    
    def validate_mirror(self, obj):

        EPS = 1e-10

        # -------------------------------------------------
        # BASIC OBJECT VALIDATION
        # -------------------------------------------------
        if obj.type != 'MESH':
            self.add_error(f"Mirror '{obj.name}' must be a MESH object.")
            return

        if not hasattr(obj, "visual_type") or int(obj.visual_type) != VISUAL_MIRROR:
            self.add_error(f"Mirror '{obj.name}' visual type must be VISUAL_MIRROR.")
            return

        if not obj.data or len(obj.data.vertices) == 0 or len(obj.data.polygons) == 0:
            self.add_error(f"Mirror '{obj.name}' mesh has no geometry.")
            return

        # -------------------------------------------------
        # VIEWBOX VALIDATION
        # -------------------------------------------------
        viewboxes = [
            c for c in obj.children
            if c.name.lower().endswith("_viewbox")
        ]

        if len(viewboxes) == 0:
            self.add_error(f"Mirror '{obj.name}' must have exactly ONE '*_viewbox' child (found none).")
            _add_fix("Add an Empty child named '<mirror>_viewbox' with CUBE display type.")
            return

        if len(viewboxes) > 1:
            names = ", ".join(v.name for v in viewboxes)
            self.add_error(f"Mirror '{obj.name}' has multiple viewboxes ({names}). Only ONE is allowed.")
            _add_fix("Remove extra viewboxes — only one '_viewbox' child per mirror.")
            return

        vb = viewboxes[0]

        # -------------------------------------------------
        # VIEWBOX OBJECT RULES
        # -------------------------------------------------
        if vb.type != 'EMPTY':
            self.add_error(f"Mirror '{obj.name}' viewbox '{vb.name}' must be an EMPTY object.")

        if vb.empty_display_type != 'CUBE':
            self.add_error(f"Mirror '{obj.name}' viewbox '{vb.name}' must use CUBE display type.")

        if vb.parent != obj:
            self.add_error(f"Mirror '{obj.name}' viewbox '{vb.name}' must be a DIRECT child of the mirror object.")

        if len(vb.children) > 0:
            self.add_error(f"Mirror '{obj.name}' viewbox '{vb.name}' must not have child objects.")

        # -------------------------------------------------
        # MIRROR ORIENTATION VALIDATION
        # -------------------------------------------------
        mesh = obj.data

        # --- Average face normal (LOCAL space) ---
        avg_normal = Vector((0.0, 0.0, 0.0))
        for poly in mesh.polygons:
            avg_normal += poly.normal

        if avg_normal.length == 0.0:
            self.add_error(f"Mirror '{obj.name}' has invalid face normals.")
            return

        avg_normal.normalize()

        expected_face = Vector((0.0, 1.0, 0.0))  # +Y

        # Face MUST point +Y
        if avg_normal.dot(expected_face) < 0.99:
            log_warn(
                f"Mirror '{obj.name}' face should point toward Local +Y.\n"
                f"Current average normal is {avg_normal}."
            )

        # -------------------------------------------------
        # LOCAL AXIS WARNINGS (NON-FATAL)
        # -------------------------------------------------
        # These do NOT stop export, but warn about flipped/rotated reflections

        # Local axes (object space)
        local_x = Vector((1.0, 0.0, 0.0))
        local_z = Vector((0.0, 0.0, 1.0))

        # +X should be LEFT (perpendicular to face, not flipped)
        if abs(local_x.dot(expected_face)) > EPS:
            log_warn(
                f"Mirror '{obj.name}' local +X axis is not perpendicular to mirror face.\n"
                "Expected +X to point left. Reflection may be mirrored sideways."
            )

        # +Z should be UP
        if local_z.dot(Vector((0.0, 0.0, 1.0))) < 0.99:
            log_warn(
                f"Mirror '{obj.name}' local +Z axis is not pointing UP.\n"
                "Reflection may appear rotated."
            )

        return True

    def validate_occluder(self, obj):
        """
        OCCLUDER (FRAME_OCCLUDER):
        - Must be CLOSED
        - Must be CONVEX
        - Faces should point OUTWARD (inward -> WARNING)
        """
        if obj.type != 'MESH':
            return

        CONVEX_TOLERANCE = 0.01
        frame_type = int(getattr(obj, "ls3d_frame_type", '1'))

        if frame_type != FRAME_OCCLUDER:
            return

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            # -------------------------------------------------
            # CLOSED MESH CHECK
            # -------------------------------------------------
            open_edges = [e for e in bm.edges if len(e.link_faces) != 2]
            if open_edges:
                self.add_error(f"Export stopped: Occluder '{obj.name}' is not a CLOSED mesh.")
                _add_fix("Close open edges on occluder meshes (no holes allowed).")
                return

            inward_ok = True
            outward_ok = True

            for face in bm.faces:
                plane_co = face.calc_center_median()
                plane_no = face.normal

                for v in bm.verts:
                    if v in face.verts:
                        continue

                    dist = (v.co - plane_co).dot(plane_no)

                    if dist < -CONVEX_TOLERANCE:
                        inward_ok = False
                    if dist > CONVEX_TOLERANCE:
                        outward_ok = False

                    if not inward_ok and not outward_ok:
                        self.add_error(f"Export stopped: Occluder '{obj.name}' is NOT convex.")
                        _add_fix("Make occluder meshes convex (use Convex Hull or simplify geometry).")
                        return

            if inward_ok and not outward_ok:
                log_warn(
                    f"Occluder '{obj.name}' faces are oriented INWARD.\n"
                    "4DS occluders are expected to face outward."
                )

        finally:
            bm.free()

    def validate_sector_and_portal(self, obj):
        """
        SECTOR (FRAME_SECTOR):
        - Must be CLOSED
        - Must be CONVEX
        - Faces should point INWARD (outward -> WARNING)

        PORTAL:
        - Must be a MESH
        - Frame type == FRAME_SECTOR
        - Parent exists and is FRAME_SECTOR
        - Name ends with _portal<number>
        - Must be PLANAR
        - Max 8 vertices
        """

        if obj.type != 'MESH':
            return

        frame_type = int(getattr(obj, "ls3d_frame_type", FRAME_VISUAL))

        is_portal = (
            obj.type == 'MESH'
                    and int(getattr(obj, "ls3d_frame_type", '1')) == FRAME_SECTOR
                    and obj.parent
                    and int(getattr(obj.parent, "ls3d_frame_type", '1')) == FRAME_SECTOR
                    and re.search(r"_portal\d+$", obj.name, re.IGNORECASE)
        )

        # Ignore non-sector meshes entirely
        if frame_type != FRAME_SECTOR:
            return

        CONVEX_TOLERANCE = 0.001
        PLANAR_EPS = 1e-10

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            # -------------------------------------------------
            # PORTAL VALIDATION
            # -------------------------------------------------
            if is_portal:
                if len(bm.verts) < 3:
                    self.add_error(f"Export stopped: Portal '{obj.name}' has too few vertices.")
                    _add_fix("Portals need at least 3 vertices.")
                    return

                if len(bm.verts) > 8:
                    self.add_error(f"Export stopped: Portal '{obj.name}' exceeds 8 vertex limit.")
                    _add_fix("Simplify portal geometry to 8 or fewer vertices.")
                    return

                # Planarity check
                v0 = bm.verts[0].co
                plane_normal = None

                for i in range(1, len(bm.verts) - 1):
                    n = (bm.verts[i].co - v0).cross(bm.verts[i + 1].co - v0)
                    if n.length > 1e-10:
                        plane_normal = n.normalized()
                        break

                if plane_normal is None:
                    self.add_error(f"Export stopped: Portal '{obj.name}' is degenerate.")
                    _add_fix("Portal vertices are collinear — reshape the portal.")
                    return

                for v in bm.verts:
                    if abs((v.co - v0).dot(plane_normal)) > PLANAR_EPS:
                        self.add_error(f"Export stopped: Portal '{obj.name}' is not planar.")
                        _add_fix("Flatten portal vertices so they all lie on a single plane.")
                        return

                return

            # -------------------------------------------------
            # SECTOR VALIDATION (REAL SECTOR ONLY)
            # -------------------------------------------------
            open_edges = [e for e in bm.edges if len(e.link_faces) != 2]
            if open_edges:
                self.add_error(f"Export stopped: Sector '{obj.name}' is not a CLOSED mesh.")
                _add_fix("Close open edges on sector meshes (no holes allowed).")
                return

            if len(bm.faces) < 4:
                self.add_error(f"Export stopped: Sector '{obj.name}' is not a volume.")
                _add_fix("Sector must be a volume with at least 4 faces.")
                return

            inward_ok = True
            outward_ok = True

            for face in bm.faces:
                plane_co = face.calc_center_median()
                plane_no = face.normal

                for v in bm.verts:
                    if v in face.verts:
                        continue

                    dist = (v.co - plane_co).dot(plane_no)

                    if dist < -CONVEX_TOLERANCE:
                        inward_ok = False
                    if dist > CONVEX_TOLERANCE:
                        outward_ok = False

                    if not inward_ok and not outward_ok:
                        self.add_error(f"Export stopped: Sector '{obj.name}' is NOT convex.")
                        _add_fix("Make sector meshes convex (use Convex Hull or simplify geometry).")
                        return

            if outward_ok and not inward_ok:
                log_warn(
                    f"Sector '{obj.name}' is convex but faces are oriented OUTWARD.\n"
                    "4DS sectors require inward-facing normals."
                )

        finally:
            bm.free()

    def validate_armature(self, armature_obj):
        """
        Validate armature structure for export.

        Rules:
          - Exactly one SINGLEMESH/SINGLEMORPH parented to the armature.
          - Exactly one blend bone (ls3d_is_blend_bone).
          - The blend bone must have the same name as the skinned mesh.
        """
        # ── Check base mesh ──────────────────────────────────────────────
        base_objects = []
        for candidate in self.objects:
            if candidate.type != 'MESH':
                continue
            vt = int(getattr(candidate, 'visual_type', -1))
            if vt not in (VISUAL_SINGLEMESH, VISUAL_SINGLEMORPH):
                continue
            if candidate.parent == armature_obj:
                base_objects.append(candidate)

        if len(base_objects) == 0:
            self.add_error(
                f"Armature '{armature_obj.name}': no SINGLEMESH/SINGLEMORPH parented to it."
            )
            _add_fix("Parent a SINGLEMESH or SINGLEMORPH mesh to the armature.")
        elif len(base_objects) > 1:
            names = ", ".join(f"'{o.name}'" for o in base_objects)
            self.add_error(
                f"Armature '{armature_obj.name}': only one skinned mesh allowed, "
                f"found {len(base_objects)}: {names}. Remove or reparent the extra meshes."
            )
            _add_fix("Remove or reparent extra skinned meshes — only one per armature.")

        # ── Check blend bone ─────────────────────────────────────────────
        blend_bones = [b for b in armature_obj.data.bones
                       if _is_blend_bone(b, armature_obj)]

        if len(blend_bones) == 0:
            log_warn(
                f"Armature '{armature_obj.name}': no blend bone. "
                f"Select a bone and mark it as blend bone in the Joint panel."
            )
        elif len(blend_bones) > 1:
            names = ", ".join(f"'{b.name}'" for b in blend_bones)
            self.add_error(
                f"Armature '{armature_obj.name}': multiple blend bones ({names}). "
                f"Only one blend bone is allowed."
            )
            _add_fix("Unmark extra blend bones — only one bone should be marked as blend.")

        # ── Check blend bone name matches skinned mesh name ──────────────
        if len(blend_bones) == 1 and len(base_objects) == 1:
            bone_name = blend_bones[0].name
            mesh_name = base_objects[0].name
            if bone_name != mesh_name:
                self.add_error(
                    f"Armature '{armature_obj.name}': blend bone '{bone_name}' must have the same name "
                    f"as the skinned mesh '{mesh_name}'. Rename the bone or the mesh to match."
                )
                _add_fix(f"Rename blend bone or skinned mesh so both are named the same.")

    def validate_joint(self, obj):
        """
        Validate skinning weights for a SINGLEMESH/SINGLEMORPH object before export.

        Rules enforced:
        - Each vertex may influence at most 2 bones.
        - If 2 bones influence a vertex, they must form a direct parent-child pair.
        - All non-zero weights on a vertex must sum to exactly 1.0 (within tolerance).

        If the corresponding addon preference is enabled, violations are auto-fixed
        instead of raising an error.
        """
        EPS = 1e-10

        # Read addon preferences for auto-fix options
        addon = bpy.context.preferences.addons.get(__name__)
        fix_multi = addon.preferences.fix_multi_influences if addon else False
        fix_nonpc = addon.preferences.fix_non_parent_child if addon else False

        # Find armature
        armature = None
        if obj.parent and obj.parent.type == 'ARMATURE':
            armature = obj.parent
        else:
            for mod in obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object:
                    armature = mod.object
                    break

        if not armature:
            return  # No armature → nothing to validate

        arm_data = armature.data

        # Build parent lookup: bone_name → parent_name or None (exclude blend bone)
        bone_parent = {b.name: (b.parent.name if b.parent else None)
                       for b in arm_data.bones if not _is_blend_bone(b, armature)}
        bone_names  = set(bone_parent.keys())

        mesh = obj.data
        vg_index_to_name = {vg.index: vg.name for vg in obj.vertex_groups}
        vg_name_to_index = {vg.name: vg.index for vg in obj.vertex_groups}

        for vi, vert in enumerate(mesh.vertices):
            # Collect only groups that correspond to actual bones
            bone_weights = [
                (vg_index_to_name[ge.group], ge.weight)
                for ge in vert.groups
                if vg_index_to_name.get(ge.group) in bone_names and ge.weight > EPS
            ]

            if not bone_weights:
                continue  # Unweighted vertex → assigned to root automatically, skip

            # Rule: max 2 bones per vertex
            if len(bone_weights) > 2:
                if fix_multi:
                    # Keep the 2 strongest influences, redistribute removed weight
                    bone_weights.sort(key=lambda x: x[1], reverse=True)
                    kept = bone_weights[:2]
                    removed = bone_weights[2:]
                    removed_names = ", ".join(f"'{n}' ({w:.4f})" for n, w in removed)
                    log_warn(
                        f"Auto-fixed vertex {vi} on '{obj.name}': removed {len(removed)} "
                        f"weakest influence(s): {removed_names}"
                    )
                    # Zero out removed groups on this vertex
                    for name, _ in removed:
                        gi = vg_name_to_index.get(name)
                        if gi is not None:
                            obj.vertex_groups[gi].remove([vi])
                    # Normalize the kept weights to sum to 1.0
                    total_kept = sum(w for _, w in kept)
                    if total_kept > EPS:
                        for name, w in kept:
                            gi = vg_name_to_index.get(name)
                            if gi is not None:
                                obj.vertex_groups[gi].add([vi], w / total_kept, 'REPLACE')
                    bone_weights = [(n, w / total_kept) for n, w in kept] if total_kept > EPS else kept
                else:
                    bone_list = ", ".join(f"'{n}' ({w:.4f})" for n, w in bone_weights)
                    self.add_error(
                        f"'{obj.name}', vertex {vi}: {len(bone_weights)} bone influences "
                        f"(max 2 allowed): {bone_list}. "
                        f"Enable 'Auto-fix >2 Bone Influences' in addon preferences to fix automatically."
                    )
                    _add_fix("Enable 'Auto-fix >2 Bone Influences' in addon preferences, or manually limit each vertex to 2 bones.")
                    continue

            # Rule: if 2 bones, they must be a direct parent-child pair
            if len(bone_weights) == 2:
                name_a, w_a = bone_weights[0]
                name_b, w_b = bone_weights[1]
                is_pc = (
                    bone_parent.get(name_a) == name_b or
                    bone_parent.get(name_b) == name_a
                )
                if not is_pc:
                    if fix_nonpc:
                        # Keep the stronger bone, remove the weaker
                        if w_a >= w_b:
                            keep_name, remove_name, remove_w = name_a, name_b, w_b
                        else:
                            keep_name, remove_name, remove_w = name_b, name_a, w_a
                        log_warn(
                            f"Auto-fixed vertex {vi} on '{obj.name}': removed non-parent-child "
                            f"bone '{remove_name}' ({remove_w:.4f}), kept '{keep_name}'"
                        )
                        gi = vg_name_to_index.get(remove_name)
                        if gi is not None:
                            obj.vertex_groups[gi].remove([vi])
                        # Set kept bone to full weight
                        gi = vg_name_to_index.get(keep_name)
                        if gi is not None:
                            obj.vertex_groups[gi].add([vi], 1.0, 'REPLACE')
                        bone_weights = [(keep_name, 1.0)]
                    else:
                        self.add_error(
                            f"'{obj.name}', vertex {vi}: weighted to non-parent-child bones "
                            f"('{name_a}', '{name_b}'). "
                            f"Enable 'Auto-fix Non-Parent-Child Weights' in addon preferences to fix automatically."
                        )
                        _add_fix("Enable 'Auto-fix Non-Parent-Child Weights' in addon preferences, or re-weight vertices to parent-child bone pairs.")

            # Rule: total weight must not exceed 1.0 for any vertex.
            total = sum(w for _, w in bone_weights)
            if total > 1.0 + 1e-6:
                bone_list = ", ".join(f"'{n}' ({w:.4f})" for n, w in bone_weights)
                self.add_error(
                    f"'{obj.name}', vertex {vi}: bone weights exceed 1.0 (got {total:.6f}). "
                    f"Influences: {bone_list}. Use 'Normalize All' in Weight Paint mode."
                )
                _add_fix("Use 'Normalize All' in Weight Paint mode to fix bone weights.")
                continue

            # Rule: two-bone vertices must sum to exactly 1.0
            if len(bone_weights) == 2 and abs(total - 1.0) > 1e-6:
                bone_list = ", ".join(f"'{n}' ({w:.4f})" for n, w in bone_weights)
                self.add_error(
                    f"'{obj.name}', vertex {vi}: two-bone weights must sum to 1.0 "
                    f"(got {total:.6f}). Influences: {bone_list}. Use 'Normalize All' in Weight Paint mode."
                )
                _add_fix("Use 'Normalize All' in Weight Paint mode to fix bone weights.")
                return

            if total < EPS:
                log_warn(
                    f"'{obj.name}', vertex {vi}: bone weights sum to zero. "
                    f"Assign a non-zero weight to at least one bone."
                )
            
    def validate_singlemesh(self, obj):
        """
        Validate a SINGLEMESH object before export.

        Rules:
          - Must have at least one vertex with bone weights (otherwise pointless as singlemesh).
          - Must NOT have shape keys with more than just the Basis key
            (if it does, it should be SINGLEMORPH instead).
        """
        EPS = 1e-10

        # Check for shape keys (morphs)
        sk = obj.data.shape_keys
        has_morphs = sk is not None and len(sk.key_blocks) > 1  # >1 because Basis always exists

        if has_morphs:
            self.add_error(
                f"Singlemesh '{obj.name}' has shape keys (morph targets). "
                f"A mesh with both weights and shape keys must be set to SINGLEMORPH, not SINGLEMESH. "
                f"Change its visual type to 'Single Morph' or remove the shape keys."
            )
            _add_fix("Change visual type to 'Single Morph', or remove shape keys.")
            return

        # Check that mesh has geometry
        if not obj.data or len(obj.data.vertices) == 0:
            self.add_error(
                f"Singlemesh '{obj.name}' has no mesh data or no vertices. "
                f"A SINGLEMESH must have a valid mesh with geometry."
            )
            _add_fix("Add geometry to the mesh or remove the empty object.")
            return

        # Check that the object is parented to an armature
        armature = None
        if obj.parent and obj.parent.type == 'ARMATURE':
            armature = obj.parent

        if not armature:
            self.add_error(
                f"Singlemesh '{obj.name}' is not parented to an armature. "
                f"A SINGLEMESH must be parented to an Armature "
                f"(select the mesh, then the armature, and Ctrl+P → Object)."
            )
            _add_fix("Parent mesh to armature: select mesh, then armature, Ctrl+P > Object.")
            return

        # Check that at least some vertices actually have bone weights
        arm_bone_names = {b.name for b in armature.data.bones
                         if not _is_blend_bone(b, armature)}

        vg_names = {vg.name for vg in obj.vertex_groups}
        weighted_bone_groups = vg_names & arm_bone_names

        has_weights = False
        if weighted_bone_groups:
            for vert in obj.data.vertices:
                for ge in vert.groups:
                    vg_name = obj.vertex_groups[ge.group].name
                    if vg_name in weighted_bone_groups and ge.weight > EPS:
                        has_weights = True
                        break
                if has_weights:
                    break

        if not has_weights:
            self.add_error(
                f"Singlemesh '{obj.name}' has no bone weights assigned. "
                f"A SINGLEMESH must have vertices weighted to bones. "
                f"Either assign weights or change its visual type to a non-skinned type."
            )
            _add_fix("Assign bone weights in Weight Paint mode, or change visual type.")


    def validate_singlemorph(self, obj):
        """
        Validate a SINGLEMORPH object before export.

        Rules:
          - Must have at least one vertex with bone weights (same as singlemesh).
          - Must have shape keys beyond just the Basis key
            (if it doesn't, it should be SINGLEMESH instead).
        """
        EPS = 1e-10

        sk = obj.data.shape_keys
        has_morphs = sk is not None and len(sk.key_blocks) > 1

        if not has_morphs:
            self.add_error(
                f"Singlemorph '{obj.name}' has no shape keys (morph targets). "
                f"A SINGLEMORPH must have at least one morph target beyond the Basis. "
                f"Add shape keys or change its visual type to 'Single Mesh'."
            )
            _add_fix("Add shape keys or change visual type to 'Single Mesh'.")
            return

        # Check that mesh has geometry
        if not obj.data or len(obj.data.vertices) == 0:
            self.add_error(
                f"Singlemorph '{obj.name}' has no mesh data or no vertices. "
                f"A SINGLEMORPH must have a valid mesh with geometry."
            )
            _add_fix("Add geometry to the mesh or remove the empty object.")
            return

        # Check that the object is parented to an armature
        armature = None
        if obj.parent and obj.parent.type == 'ARMATURE':
            armature = obj.parent

        if not armature:
            self.add_error(
                f"Singlemorph '{obj.name}' is not parented to an armature. "
                f"A SINGLEMORPH must be parented to an Armature "
                f"(select the mesh, then the armature, and Ctrl+P → Object)."
            )
            _add_fix("Parent mesh to armature: select mesh, then armature, Ctrl+P > Object.")
            return

        arm_bone_names = {b.name for b in armature.data.bones
                         if not _is_blend_bone(b, armature)}
        weighted_bone_groups = {vg.name for vg in obj.vertex_groups} & arm_bone_names

        has_weights = False
        if weighted_bone_groups:
            for vert in obj.data.vertices:
                for ge in vert.groups:
                    if obj.vertex_groups[ge.group].name in weighted_bone_groups and ge.weight > EPS:
                        has_weights = True
                        break
                if has_weights:
                    break

        if not has_weights:
            self.add_error(
                f"Singlemorph '{obj.name}' has no bone weights assigned. "
                f"A SINGLEMORPH must have vertices weighted to bones. "
                f"Either assign weights or remove the shape keys and use a non-skinned morph type."
            )
            _add_fix("Assign bone weights in Weight Paint mode, or change visual type.")


    # def serialize_morph(self, f, obj, lods, lod_mappings):
    #     """
    #     Serialize VISUAL_MORPH (4DS v29).
    #     - Iterates over the LOD objects provided.
    #     - Uses Vertex Map from BMesh exporter.
    #     - Exports EXACT values (No Rounding).
    #     """
        
    #     # 1. HEADER (Based on Main Object for target count)
    #     main_mesh = obj.data
        
    #     # If main object has no keys, we can't define targets.
    #     if not main_mesh.shape_keys or len(main_mesh.shape_keys.key_blocks) == 0:
    #         f.write(struct.pack("<B", 0))
    #         return

    #     # We use the Main Object to define the "Global" list of targets
    #     # (Basis + Sliders)
    #     main_keys = list(main_mesh.shape_keys.key_blocks)
        
    #     num_targets = len(main_keys) 
    #     num_regions = 1
    #     # STRICTLY follow the number of LODs passed in
    #     num_lods = len(lods) 

    #     f.write(struct.pack("<B", num_targets))
    #     f.write(struct.pack("<B", num_regions))
    #     f.write(struct.pack("<B", num_lods))

    #     # ------------------------------------------------
    #     # LOOP THROUGH PROVIDED LODS
    #     # ------------------------------------------------
    #     for i, current_obj in enumerate(lods):
            
    #         mapping = lod_mappings[i]
    #         mesh = current_obj.data
            
    #         # Does this LOD have shape keys?
    #         has_keys = (mesh.shape_keys and len(mesh.shape_keys.key_blocks) > 0)
            
    #         active_game_indices = set()
            
    #         # 1. IDENTIFY CHANGED INDICES
    #         if has_keys:
    #             current_keys = mesh.shape_keys.key_blocks
    #             # Assume Index 0 is Basis
    #             base_key = current_keys[0]

    #             # We iterate the MAIN keys to keep target order (Basis, Key1, Key2...)
    #             for k_idx, main_k in enumerate(main_keys):
    #                 if k_idx == 0:
    #                     continue

    #                 key = current_keys.get(main_k.name)
    #                 if not key:
    #                     continue

    #                 for v_idx in range(len(mesh.vertices)):

    #                     if base_key.data[v_idx].co != key.data[v_idx].co:

    #                         if v_idx in mapping:
    #                             for game_index in mapping[v_idx]:
    #                                 active_game_indices.add(game_index)


    #         sorted_game_verts = sorted(list(active_game_indices))
    #         num_verts_out = len(sorted_game_verts)
            
    #         f.write(struct.pack("<H", num_verts_out))
            
    #         # 2. WRITE DATA
    #         # Reverse Map
    #         game_to_orig = {}
    #         for orig, game_indices in mapping.items():
    #             for g_idx in game_indices:
    #                 game_to_orig[g_idx] = orig
            
    #         vmin = None
    #         vmax = None

    #         for game_vert_id in sorted_game_verts:
    #             orig_vert_id = game_to_orig[game_vert_id]
                
    #             # Basis Normal
    #             b_norm = mesh.vertices[orig_vert_id].normal
    #             nx, ny, nz = b_norm.x, b_norm.z, b_norm.y

    #             # Write data for EVERY target defined in Header
    #             if has_keys:
    #                 current_keys = mesh.shape_keys.key_blocks
    #                 base_key = current_keys[0]

    #                 for k_idx, main_k in enumerate(main_keys):
    #                     # Find Key
    #                     key = current_keys.get(main_k.name)
    #                     if not key and k_idx < len(current_keys):
    #                         key = current_keys[k_idx]
                        
    #                     # Missing key fallback
    #                     if not key: key = base_key

    #                     # RAW COORDS
    #                     co = key.data[orig_vert_id].co
                        
    #                     px = co.x
    #                     py = co.z
    #                     pz = co.y

    #                     f.write(struct.pack("<3f", px, py, pz))
    #                     f.write(struct.pack("<3f", nx, ny, nz))

    #                     # Bounds
    #                     if vmin is None:
    #                         vmin = Vector((px, py, pz))
    #                         vmax = Vector((px, py, pz))
    #                     else:
    #                         if px < vmin.x: vmin.x = px
    #                         if py < vmin.y: vmin.y = py
    #                         if pz < vmin.z: vmin.z = pz
    #                         if px > vmax.x: vmax.x = px
    #                         if py > vmax.y: vmax.y = py
    #                         if pz > vmax.z: vmax.z = pz
            
    #         # Unknown Flag
    #         if num_verts_out * num_targets > 0:
    #             f.write(struct.pack("<B", 1))
            
    #         # 3. WRITE INDICES
    #         for game_vert_id in sorted_game_verts:
    #             f.write(struct.pack("<H", game_vert_id))

    #     # 4. GLOBAL BOUNDS
    #     if vmin is None:
    #         vmin = Vector((0, 0, 0))
    #         vmax = Vector((0, 0, 0))

    #     center = (vmin + vmax) * 0.5
    #     radius = (vmax - vmin).length * 0.5

    #     f.write(struct.pack("<3f", vmin.x, vmin.y, vmin.z))
    #     f.write(struct.pack("<3f", vmax.x, vmax.y, vmax.z))
    #     f.write(struct.pack("<3f", center.x, center.y, center.z))
    #     f.write(struct.pack("<f", radius))

    def validate_morph(self, obj, lods):
        """Hard-error pre-flight check for morph/singlemorph frames.

        Called from serialize_frame before serialize_morph, alongside the other
        validate_* functions.  Raises RuntimeError on structural problems that
        must block export.  Soft/recoverable conditions (no targets yet, no
        matching shape keys on any LOD) are left to serialize_morph so it can
        write numTargets=0 gracefully.
        """
        vt      = int(getattr(obj, 'visual_type', 0))
        vt_name = {VISUAL_SINGLEMORPH: "Single Morph",
                   VISUAL_MORPH:       "Morph"}.get(vt, "Morph")
        groups  = obj.ls3d_morph_groups

        # Hard error: morph type set but no groups defined at all
        if not groups:
            self.add_error(
                f"'{obj.name}' is set to '{vt_name}' but has no morph groups defined. "
                f"Add morph groups in the 4DS panel, or change the visual type."
            )
            _add_fix("Add morph groups in the 4DS panel, or change the visual type.")
            return

        # Warning: groups exist but no targets assigned yet
        num_targets = max((len(g.targets) for g in groups), default=0)
        if num_targets == 0:
            log_warn(
                f"'{obj.name}' is set to '{vt_name}' but no targets have been added to "
                f"any morph group. No morph data will be written."
            )

        # Hard error: every group with targets must have a resolvable basis key
        for lod_obj in lods:
            sk = lod_obj.data.shape_keys
            if not sk:
                continue
            for g in groups:
                if not g.targets:
                    continue
                basis_name = g.targets[0].shape_key_name
                if not sk.key_blocks.get(basis_name):
                    self.add_error(
                        f"Morph group '{g.name}': basis shape key '{basis_name}' not "
                        f"found on '{lod_obj.name}'. Every group must have a valid basis "
                        f"key as its first target. Fix the shape key name or assign a "
                        f"different key."
                    )
                    _add_fix("Fix shape key names in morph groups to match actual shape keys.")

        # Warning: no LOD mesh contains any of the referenced shape keys
        has_any = any(
            lod_obj.data.shape_keys and
            any(lod_obj.data.shape_keys.key_blocks.get(t.shape_key_name)
                for g in groups for t in g.targets)
            for lod_obj in lods
        )
        if num_targets > 0 and not has_any:
            log_warn(
                f"'{obj.name}' is set to '{vt_name}' but none of the shape keys "
                f"referenced in the morph groups were found on any LOD mesh. "
                f"No morph data will be written. Check that the shape key names in "
                f"the 4DS morph panel match the actual shape key names on the mesh."
            )

    def serialize_morph(self, f, obj, lods, lod_mappings):
        vt      = int(getattr(obj, 'visual_type', 0))
        vt_name = {VISUAL_SINGLEMORPH: "Single Morph",
                   VISUAL_MORPH:       "Morph"}.get(vt, "Morph")
        groups  = obj.ls3d_morph_groups

        num_targets = max((len(g.targets) for g in groups), default=0)
        if num_targets == 0:
            f.write(struct.pack("<B", 0))
            return

        active_lods = []
        for lod_i, lod_obj in enumerate(lods):
            sk = lod_obj.data.shape_keys
            if not sk:
                continue
            if any(sk.key_blocks.get(t.shape_key_name)
                   for g in groups for t in g.targets):
                active_lods.append((lod_i, lod_obj))

        if not active_lods:
            f.write(struct.pack("<B", 0))
            return

        num_regions = len(groups)

        f.write(struct.pack("<B", num_targets))
        f.write(struct.pack("<B", num_regions))
        f.write(struct.pack("<B", len(active_lods)))

        vmin = vmax = None

        for lod_i, lod_obj in active_lods:
            sk      = lod_obj.data.shape_keys
            mapping = lod_mappings[lod_i]

            game_to_orig = {}
            for orig, game_list in mapping.items():
                for gi in game_list:
                    game_to_orig[gi] = orig

            # Float-noise floor — not exposed in UI.  1e-4 Mafia units (0.1 mm)
            # is far below the smallest intentional facial movement.
            NOISE_FLOOR = 1e-8

            # ── Pass 1: collect per-group data (resolved targets + max-delta map) ─
            # Each entry: (g, resolved_keys, orig_max_delta_dict)
            group_data = []
            for g in groups:
                ref_key = sk.key_blocks.get(g.targets[0].shape_key_name) if g.targets else None

                resolved = []
                for t in g.targets:
                    k = sk.key_blocks.get(t.shape_key_name) or ref_key
                    resolved.append(k)
                while len(resolved) < num_targets:
                    resolved.append(ref_key)

                orig_max_delta = {}   # orig_vi → max component delta across all targets

                if ref_key is not None:
                    for tkey in resolved[1:]:
                        if tkey and tkey is not ref_key:
                            for vi in range(len(lod_obj.data.vertices)):
                                rc = ref_key.data[vi].co
                                tc = tkey.data[vi].co
                                d = max(abs(rc.x - tc.x),
                                        abs(rc.y - tc.y),
                                        abs(rc.z - tc.z))
                                if d > NOISE_FLOOR:
                                    if d > orig_max_delta.get(vi, 0.0):
                                        orig_max_delta[vi] = d

                group_data.append((g, resolved, orig_max_delta))

            # ── Pass 2: deduplicate across regions ─────────────────────────────
            # The game engine applies regions sequentially; the last region to
            # reference a vertex WINS (overwrites all earlier writes for that vert).
            # Regions must therefore be disjoint so a later region's basis position
            # for a target it doesn't use doesn't overwrite what an earlier region
            # correctly wrote.  We enforce the same guarantee here: assign each original
            # vertex to exactly the one region where it has the largest movement
            # from basis (largest-delta-wins; ties go to the lower-index region).
            # No vertex data is lost — every vertex that moved in any group is still
            # written, just into one region instead of potentially several.
            vertex_owner = {}   # orig_vi → group_index
            for gi, (_g, _resolved, omd) in enumerate(group_data):
                for vi, delta in omd.items():
                    prev = vertex_owner.get(vi)
                    if prev is None or delta > group_data[prev][2].get(vi, 0.0):
                        vertex_owner[vi] = gi

            deduped_orig = [set() for _ in groups]
            for vi, gi in vertex_owner.items():
                deduped_orig[gi].add(vi)

            # ── Pass 3: write each region using its deduplicated vertex set ────
            for gi, (g, resolved, _omd) in enumerate(group_data):
                # Expand original vertex indices → game buffer indices
                changed = set()
                for vi in deduped_orig[gi]:
                    for game_idx in mapping.get(vi, []):
                        changed.add(game_idx)

                sorted_verts = sorted(changed)
                f.write(struct.pack("<H", len(sorted_verts)))

                if not sorted_verts:
                    continue

                for gv in sorted_verts:
                    orig = game_to_orig[gv]
                    n    = lod_obj.data.vertices[orig].normal
                    nx, ny, nz = n.x, n.z, n.y  # Y↔Z

                    for tkey in resolved:
                        co = tkey.data[orig].co if tkey else Vector((0, 0, 0))
                        px, py, pz = co.x, co.z, co.y  # Y↔Z
                        f.write(struct.pack("<3f", px, py, pz))
                        f.write(struct.pack("<3f", nx, ny, nz))

                        if vmin is None:
                            vmin = Vector((px, py, pz))
                            vmax = Vector((px, py, pz))
                        else:
                            vmin.x = min(vmin.x, px); vmax.x = max(vmax.x, px)
                            vmin.y = min(vmin.y, py); vmax.y = max(vmax.y, py)
                            vmin.z = min(vmin.z, pz); vmax.z = max(vmax.z, pz)

                f.write(struct.pack("<B", 1))  # flag: explicit indices follow
                for gv in sorted_verts:
                    f.write(struct.pack("<H", gv))

        if vmin is None:
            vmin = vmax = Vector((0, 0, 0))
        center = (vmin + vmax) * 0.5
        radius = (vmax - vmin).length * 0.5
        f.write(struct.pack("<3f", vmin.x, vmin.y, vmin.z))
        f.write(struct.pack("<3f", vmax.x, vmax.y, vmax.z))
        f.write(struct.pack("<3f", center.x, center.y, center.z))
        f.write(struct.pack("<f",  radius))

    def serialize_dummy(self, f, obj):
        # 1. Get Local Bounds (Unscaled by Object Transform)
        if "bbox_min" in obj and "bbox_max" in obj:
            # Use stored values from Import or UI
            # Blender Space (X, Y, Z)
            min_v = Vector(obj["bbox_min"])
            max_v = Vector(obj["bbox_max"])
        else:
            # Fallback for new objects: Create a centered box based on visual display size
            # We assume a cube for new objects
            s = obj.empty_display_size
            min_v = Vector((-s, -s, -s))
            max_v = Vector((s, s, s))

        # 2. Convert to Mafia Space (Swap Y and Z)
        # Blender (X, Y, Z) -> Mafia (X, Z, Y)
        # We write Min then Max
        f.write(struct.pack("<3f", min_v.x, min_v.z, min_v.y)) 
        f.write(struct.pack("<3f", max_v.x, max_v.z, max_v.y))
        
    def serialize_target(self, f, obj):
        flags = getattr(obj, "ls3d_target_flags", 1)
        f.write(struct.pack("<H", flags))

        link_ids = []
        for entry in obj.ls3d_target_objects:
            # ── Bone target ──
            if entry.target_armature and entry.bone_name:
                arm = entry.target_armature
                fid = self.frames_map.get((arm, entry.bone_name))
                if fid is not None:
                    link_ids.append(fid)
                else:
                    log_warn(f"Target '{obj.name}' bone link '{entry.bone_name}' on '{arm.name}' has no frame ID — skipped")
                continue

            # ── Object target (pointer) ──
            target_obj = entry.target_object
            if target_obj is None:
                # Legacy fallback: try target_path string
                path = entry.target_path
                if path.startswith("BONE:"):
                    parts = path.split(":", 2)
                    if len(parts) == 3:
                        arm_obj = bpy.data.objects.get(parts[1])
                        fid = self.frames_map.get((arm_obj, parts[2])) if arm_obj else None
                        if fid is not None:
                            link_ids.append(fid)
                        else:
                            log_warn(f"Target '{obj.name}' bone link '{parts[2]}' has no frame ID — skipped")
                    continue
                target_obj = bpy.data.objects.get(path)

            if target_obj is None:
                log_warn(f"Target '{obj.name}' has unresolved link — skipped")
                continue
            fid = self.frames_map.get(target_obj)
            if fid is None:
                log_warn(f"Target '{obj.name}' links to '{target_obj.name}' which has no frame ID — skipped")
                continue
            link_ids.append(fid)

        f.write(struct.pack("<B", len(link_ids)))
        for fid in link_ids:
            f.write(struct.pack("<H", fid))

    def serialize_occluder(self, f, obj):
        # 1. Get evaluated mesh
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()

        # Ensure triangles
        mesh.calc_loop_triangles()

        # 2. Write counts
        f.write(struct.pack("<I", len(mesh.vertices)))
        f.write(struct.pack("<I", len(mesh.loop_triangles)))

        # 3. Write vertices (STABLE ORDER)
        for v in mesh.vertices:
            f.write(struct.pack("<3f", v.co.x, v.co.z, v.co.y))

        # 4. Write faces (loop triangles)
        for tri in mesh.loop_triangles:
            v0, v1, v2 = tri.vertices
            # Mafia winding: (0,2,1)
            f.write(struct.pack("<3H", v0, v2, v1))

        # Cleanup
        eval_obj.to_mesh_clear()
    
    def serialize_joints(self, f, armature_obj):

        arm_data = armature_obj.data

        # Use bone.matrix_local directly (edit-bone rest data, NEVER affected
        # by animation).  Do NOT multiply by armature_obj.matrix_world — that
        # includes animated object-level transforms from 5DS.
        # bone.matrix_local is the bone's transform in armature-local space,
        # which equals the noscale world position because the armature was
        # created at the origin during import.

        # DFS — identical sort/stack to the pre-scan in execute() so frame IDs
        # are consumed in the same order they were assigned.
        # Exclude blend bone from traversal — it is NOT a FRAME_JOINT.
        roots = sorted(
            [b for b in arm_data.bones
             if not _is_blend_bone(b, armature_obj)
             and (b.parent is None or _is_blend_bone(b.parent, armature_obj))],
            key=lambda b: b.name
        )
        ordered = []
        stack   = list(reversed(roots))
        while stack:
            bone = stack.pop()
            ordered.append(bone)
            stack.extend(reversed(sorted(
                [c for c in bone.children if not _is_blend_bone(c, armature_obj)],
                key=lambda b: b.name)))

        frame_id_map = {}
        for bone in ordered:
            fid = self.frames_map[(armature_obj, bone.name)]
            frame_id_map[bone.name] = fid
            self.frame_index += 1

        skin_obj      = None
        skin_frame_id = 0
        for candidate in self.objects:
            vt = int(getattr(candidate, 'visual_type', -1))
            if vt not in (VISUAL_SINGLEMESH, VISUAL_SINGLEMORPH):
                continue
            if any(m.type == 'ARMATURE' and m.object == armature_obj
                   for m in candidate.modifiers):
                skin_obj      = candidate
                skin_frame_id = self.frames_map.get(candidate, 0)
                break
            if candidate.parent == armature_obj:
                skin_obj      = candidate
                skin_frame_id = self.frames_map.get(candidate, 0)
                break

        # Skin mesh transform in armature-local space (animation-immune).
        # matrix_parent_inverse was set when the mesh was parented to the
        # armature during import; matrix_basis is the mesh's own transform.
        if skin_obj and skin_obj.parent == armature_obj:
            skin_local = skin_obj.matrix_parent_inverse @ skin_obj.matrix_basis
        elif skin_obj:
            skin_local = skin_obj.matrix_world.copy()
        else:
            skin_local = Matrix.Identity(4)

        for bone in ordered:
            joint_id_raw    = self.joint_maps[armature_obj][bone.name] - 1
            # Skip blend bone in parent chain for frame ID lookup
            parent_bone = bone.parent
            if parent_bone and _is_blend_bone(parent_bone, armature_obj):
                parent_bone = None
            parent_frame_id = (
                frame_id_map[parent_bone.name] if parent_bone else skin_frame_id
            )

            # bone.matrix_local = noscale rest transform in armature space
            bw_loc, bw_rot, _ = bone.matrix_local.decompose()

            # Recover local T/R from Blender edit-bone data.
            # bone.matrix_local already encodes the accumulated world rotation
            # in armature space, so we only need the direct parent's decomposed
            # rotation — no need to walk the full ancestor chain.
            if parent_bone:
                pw_loc, pw_rot, _ = parent_bone.matrix_local.decompose()
                loc = pw_rot.to_matrix().inverted() @ (bw_loc - pw_loc)
                rot = pw_rot.inverted() @ bw_rot
            else:
                sw_loc, sw_rot, _ = skin_local.decompose()
                loc = sw_rot.to_matrix().inverted() @ (bw_loc - sw_loc)
                rot = sw_rot.inverted() @ bw_rot

            pb      = armature_obj.pose.bones.get(bone.name)
            raw_scl = pb.get("ls3d_joint_scale", (1.0, 1.0, 1.0)) if pb else (1.0, 1.0, 1.0)
            scl     = Vector(raw_scl)

            # Use the precomputed full-scale world matrix for the inv_bind.
            bone_world_full = self.bone_full_world.get((armature_obj, bone.name))
            if bone_world_full is not None:
                inv_bind = bone_world_full.inverted() @ skin_local
            else:
                inv_bind = Matrix.LocRotScale(bw_loc, bw_rot, scl).inverted() @ skin_local

            cull_flags = 0
            user_props = ""
            if pb is not None:
                cull_flags = pb.cull_flags
                user_props = pb.user_props

            f.write(struct.pack("<B",  FRAME_JOINT))
            f.write(struct.pack("<H",  parent_frame_id))
            f.write(struct.pack("<3f", loc.x, loc.z, loc.y))
            f.write(struct.pack("<3f", scl.x, scl.z, scl.y))
            f.write(struct.pack("<4f", rot.w, rot.x, rot.z, rot.y))
            f.write(struct.pack("<B",  cull_flags))
            self.write_string(f, bone.name)
            self.write_string(f, user_props)

            X, Y, Z, T = inv_bind.col[0], inv_bind.col[1], inv_bind.col[2], inv_bind.col[3]
            f.write(struct.pack("<16f",
                X[0], X[2], X[1], 0.0,
                Z[0], Z[2], Z[1], 0.0,
                Y[0], Y[2], Y[1], 0.0,
                T[0], T[2], T[1], 1.0,
            ))

            f.write(struct.pack("<I", joint_id_raw))

    def serialize_singlemesh(self, f, all_lod_skin):
        """Write skin block for all LODs.  Mesh geometry is written by
        serialize_object (called with armature parameter)."""
        for skin in all_lod_skin:
            if skin is None:
                f.write(struct.pack("<B", 0))
                f.write(struct.pack("<I", 0))
                f.write(struct.pack("<6f", 0, 0, 0, 0, 0, 0))
                continue

            f.write(struct.pack("<B", skin['num_groups']))
            f.write(struct.pack("<I", skin['root_noW']))
            f.write(struct.pack("<3f", *skin['r_min']))
            f.write(struct.pack("<3f", *skin['r_max']))

            for g in skin['groups']:
                M = g['inv_bind']
                X, Y, Z, T = M.col[0], M.col[1], M.col[2], M.col[3]
                f.write(struct.pack("<16f",
                    X[0], X[2], X[1], 0.0,
                    Z[0], Z[2], Z[1], 0.0,
                    Y[0], Y[2], Y[1], 0.0,
                    T[0], T[2], T[1], 1.0,
                ))
                f.write(struct.pack("<I", g['noW']))
                f.write(struct.pack("<I", g['W']))
                f.write(struct.pack("<I", g['par']))
                f.write(struct.pack("<3f", *g['b_min']))
                f.write(struct.pack("<3f", *g['b_max']))
                for w in g['weights']:
                    f.write(struct.pack("<f", w))
    
    def serialize_frame(self, f, obj):

        # ── Armature: write each bone as a FRAME_JOINT frame ─────────────────
        if obj.type == 'ARMATURE':
            self.validate_armature(obj)
            self.raise_if_errors()
            self.serialize_joints(f, obj)
            return

        frame_type = int(getattr(obj, "ls3d_frame_type", FRAME_VISUAL))

        # Mirror viewboxes are embedded in the mirror payload, not separate frames.
        if (
            obj.type == 'EMPTY'
            and obj.empty_display_type == 'CUBE'
            and frame_type == FRAME_DUMMY
            and obj.name.lower().endswith("_viewbox")
            and obj.parent
            and hasattr(obj.parent, "visual_type")
            and int(getattr(obj.parent, "visual_type", -1)) == VISUAL_MIRROR
        ):
            return

        visual_type  = 0
        visual_flags = (0, 0)
        if frame_type == FRAME_VISUAL:
            visual_type  = int(getattr(obj, "visual_type", 0))
            visual_flags = (
                getattr(obj, "render_flags",  0),
                getattr(obj, "render_flags2", 0),
            )

        self.frame_index += 1

        # ── Parent resolution ─────────────────────────────────────────────────
        parent_id    = 0

        if obj.parent:
            if obj.parent_type == 'BONE' and obj.parent_bone:
                bone_name = obj.parent_bone
                arm  = obj.parent
                parent_id = self.frames_map.get((arm, bone_name), 0)
                bone = arm.data.bones.get(bone_name)
                if bone:
                    # Compute the REST-pose child world using bone.matrix_local
                    # (edit-bone data, never affected by animation) and the
                    # object's own matrix_parent_inverse + matrix_basis.
                    bone_rest = bone.matrix_local
                    obj_rest_world = (
                        bone_rest
                        @ Matrix.Translation((0, bone.length, 0))
                        @ obj.matrix_parent_inverse
                        @ obj.matrix_basis
                    )

                    # Use precomputed full-scale world matrix for the bone.
                    bone_4ds_world = self.bone_full_world.get((arm, bone.name))
                    if bone_4ds_world is None:
                        bone_4ds_world = bone_rest  # fallback: noscale

                    file_local = bone_4ds_world.inverted() @ obj_rest_world
                    loc, rot, scl = file_local.decompose()
                else:
                    loc, rot, scl = (obj.matrix_parent_inverse @ obj.matrix_basis).decompose()
            elif obj.parent.type == 'ARMATURE':
                # Skin mesh parented to armature — use animation-immune local
                # transform.  parent_id stays 0 (armature is not a 4DS frame).
                loc, rot, scl = (obj.matrix_parent_inverse @ obj.matrix_basis).decompose()
            elif obj.parent in self.frames_map:
                parent_id     = self.frames_map[obj.parent]
                loc, rot, scl = (obj.parent.matrix_world.inverted() @ obj.matrix_world).decompose()
            else:
                loc, rot, scl = obj.matrix_world.decompose()
        else:
            loc, rot, scl = obj.matrix_world.decompose()

        # ── Write frame header ────────────────────────────────────────────────
        f.write(struct.pack("<B", frame_type))
        if frame_type == FRAME_VISUAL:
            f.write(struct.pack("<B",  visual_type))
            f.write(struct.pack("<2B", *visual_flags))
        f.write(struct.pack("<H",  parent_id))
        f.write(struct.pack("<3f", loc.x, loc.z, loc.y))
        f.write(struct.pack("<3f", scl.x, scl.z, scl.y))
        f.write(struct.pack("<4f", rot.w, rot.x, rot.z, rot.y))
        f.write(struct.pack("<B",  getattr(obj, "cull_flags", 0)))
        self.write_string(f, obj.name)
        self.write_string(f, getattr(obj, "ls3d_user_props", ""))

        # ── Write frame payload ───────────────────────────────────────────────
        if frame_type == FRAME_VISUAL:
            lods = self.lod_map.get(obj, [obj])

            if visual_type == VISUAL_LENSFLARE:
                self.serialize_lensflare(f, obj)

            elif visual_type == VISUAL_MIRROR:
                self.validate_mirror(obj)
                self.serialize_mirror(f, obj)

            elif visual_type == VISUAL_SINGLEMESH:
                self.validate_singlemesh(obj)
                self.validate_joint(obj)
                self.raise_if_errors()
                armature = obj.parent if (obj.parent and obj.parent.type == 'ARMATURE') else None
                _, _, all_lod_skin = self.serialize_object(f, obj, lods, armature=armature)
                self.serialize_singlemesh(f, all_lod_skin)

            elif visual_type == VISUAL_SINGLEMORPH:
                self.validate_singlemorph(obj)
                self.validate_morph(obj, lods)
                self.validate_joint(obj)
                self.raise_if_errors()
                armature = obj.parent if (obj.parent and obj.parent.type == 'ARMATURE') else None
                _, lod_mappings, all_lod_skin = self.serialize_object(f, obj, lods, armature=armature)
                self.serialize_singlemesh(f, all_lod_skin)
                self.serialize_morph(f, obj, lods, lod_mappings)

            elif visual_type == VISUAL_BILLBOARD:
                self.validate_billboard(obj)
                self.serialize_object(f, obj, lods)
                self.serialize_billboard(f, obj)

            elif visual_type == VISUAL_MORPH:
                self.validate_morph(obj, lods)
                _, lod_mappings = self.serialize_object(f, obj, lods)
                self.serialize_morph(f, obj, lods, lod_mappings)

            else:
                self.serialize_object(f, obj, lods)

        elif frame_type == FRAME_SECTOR:
            self.validate_sector_and_portal(obj)
            self.serialize_sector(f, obj)
        elif frame_type == FRAME_DUMMY:
            self.serialize_dummy(f, obj)
        elif frame_type == FRAME_TARGET:
            self.serialize_target(f, obj)
        elif frame_type == FRAME_OCCLUDER:
            self.validate_occluder(obj)
            self.serialize_occluder(f, obj)

    def get_ordered_portal_verts(self, obj):
        # 1. Evaluate Mesh
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            is_temp_mesh = True
        except:
            mesh = obj.data.copy()
            is_temp_mesh = False

        mesh.transform(obj.matrix_world)

        # 2. Create BMesh to Process Geometry
        bm = bmesh.new()
        bm.from_mesh(mesh)
        
        # 3. CONVERT TO N-GON (Dissolve Logic)
        # This fixes issues where a quad portal is split into 2 tris, counting 6 verts instead of 4.
        
        # A. Remove Doubles
      # bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
        
        # B. Dissolve Internal Edges/Faces to create one boundary face
        # We try to dissolve everything into as few faces as possible.
        # If the portal is flat and contiguous, this results in 1 Face.
        bmesh.ops.dissolve_faces(bm, faces=bm.faces)
        
        # 4. Extract Perimeter Vertices
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        raw_verts = []
        normal = Vector((0,0,0))
        
        # If successful, we should have 1 face
        if len(bm.faces) > 0:
            # Take the largest face if there are disjoint parts (error case, but handle it)
            target_face = max(bm.faces, key=lambda f: f.calc_area())
            normal = target_face.normal.copy()
            
            for v in target_face.verts:
                raw_verts.append(v.co.copy())
        
        bm.free()

        # 5. Cleanup Temp Mesh
        if is_temp_mesh:
            eval_obj.to_mesh_clear()
        else:
            bpy.data.meshes.remove(mesh)

        if len(raw_verts) < 3:
            return [], Vector((0,1,0)), Vector((0,0,0))

        # 6. Angular Sort (Standard Convex Hull sort to match standard)
        center = sum(raw_verts, Vector()) / len(raw_verts)
        up = Vector((0, 0, 1))
        if abs(normal.dot(up)) > 0.99: up = Vector((0, 1, 0))
        
        tangent = normal.cross(up).normalized()
        bitangent = normal.cross(tangent).normalized()

        def get_angle(v):
            vec = v - center
            return math.atan2(vec.dot(bitangent), vec.dot(tangent))

        raw_verts.sort(key=get_angle)

        return raw_verts, normal, center
    
    def serialize_sector(self, f, obj):

        # -------------------------------------------------
        # 1. FLAGS
        # -------------------------------------------------
        f1 = getattr(obj, "ls3d_sector_flags1", 0)
        f2 = getattr(obj, "ls3d_sector_flags2", 0)
        f.write(struct.pack("<2i", f1, f2))

        # -------------------------------------------------
        # 2. GEOMETRY
        # -------------------------------------------------
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()

        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bmesh.ops.triangulate(bm, faces=bm.faces)

            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            num_verts = len(bm.verts)
            num_faces = len(bm.faces)

            f.write(struct.pack("<I", num_verts))
            f.write(struct.pack("<I", num_faces))

            min_b = [float('inf')] * 3
            max_b = [float('-inf')] * 3

            world = obj.matrix_world

            for v in bm.verts:
                v_world = world @ v.co
                vx, vy, vz = v_world.x, v_world.z, v_world.y

                f.write(struct.pack("<3f", vx, vy, vz))

                min_b[0] = min(min_b[0], vx)
                min_b[1] = min(min_b[1], vy)
                min_b[2] = min(min_b[2], vz)
                max_b[0] = max(max_b[0], vx)
                max_b[1] = max(max_b[1], vy)
                max_b[2] = max(max_b[2], vz)

            for face in bm.faces:
                v = face.verts
                f.write(struct.pack("<3H", v[0].index, v[2].index, v[1].index))

        finally:
            bm.free()
            eval_obj.to_mesh_clear()

        # -------------------------------------------------
        # 3. BBOX
        # -------------------------------------------------
        if num_verts > 0:
            f.write(struct.pack("<3f", *min_b))
            f.write(struct.pack("<3f", *max_b))
        else:
            f.write(struct.pack("<6f", 0, 0, 0, 0, 0, 0))

        # -------------------------------------------------
        # 4. PORTALS
        # -------------------------------------------------
        portals = []

        for child in obj.children:
            try:
                ftype = int(child.ls3d_frame_type)
            except:
                ftype = 0
            if ftype == FRAME_SECTOR and re.search(r"_portal\d+$", child.name, re.IGNORECASE):
                portals.append(child)

        portals.sort(key=lambda o: o.name)
        f.write(struct.pack("<B", len(portals)))

        for p_obj in portals:

            flags = getattr(p_obj, "ls3d_portal_flags", 0)
            near = getattr(p_obj, "ls3d_portal_near", 0.0)
            far  = getattr(p_obj, "ls3d_portal_far", 0.0)

            verts, _, _ = self.get_ordered_portal_verts(p_obj)

            # Empty portal
            if len(verts) < 3:
                f.write(struct.pack("<B", 0))
                f.write(struct.pack("<I", flags))
                f.write(struct.pack("<f", near))
                f.write(struct.pack("<f", far))
                f.write(struct.pack("<3f", 0.0, 0.0, 0.0))
                f.write(struct.pack("<f", 0.0))
                continue

            # Convert verts to Mafia space
            mafia_verts = [Vector((v.x, v.z, v.y)) for v in verts]

            # -------------------------------------------------
            # USE STORED PLANE IF AVAILABLE
            # -------------------------------------------------
            if hasattr(p_obj, "ls3d_portal_normal") and hasattr(p_obj, "ls3d_portal_dot"):

                nx, ny, nz = p_obj.ls3d_portal_normal
                d = p_obj.ls3d_portal_dot

            else:
                # Only calculate for newly created portals

                v0 = mafia_verts[0]
                v1 = mafia_verts[1]
                v2 = mafia_verts[2]

                edge1 = v1 - v0
                edge2 = v2 - v0

                normal = edge1.cross(edge2)

                # DO NOT normalize - preserve magnitude
                nx, ny, nz = normal.x, normal.y, normal.z
                d = -normal.dot(v0)

            # -------------------------------------------------
            # WRITE PORTAL
            # -------------------------------------------------
            f.write(struct.pack("<B", len(mafia_verts)))
            f.write(struct.pack("<I", flags))
            f.write(struct.pack("<f", near))
            f.write(struct.pack("<f", far))

            f.write(struct.pack("<3f", nx, ny, nz))
            f.write(struct.pack("<f", d))

            for v in mafia_verts:
                f.write(struct.pack("<3f", v.x, v.y, v.z))

    # def serialize_sector(self, f, obj):
    #     # -------------------------------------------------
    #     # 1. FLAGS
    #     # -------------------------------------------------
    #     f1 = getattr(obj, "ls3d_sector_flags1", 0)
    #     f2 = getattr(obj, "ls3d_sector_flags2", 0)
    #     f.write(struct.pack("<2i", f1, f2))

    #     # -------------------------------------------------
    #     # 2. GEOMETRY (EVALUATED, TRIANGULATED)
    #     # -------------------------------------------------
    #     depsgraph = bpy.context.evaluated_depsgraph_get()
    #     eval_obj = obj.evaluated_get(depsgraph)
    #     mesh = eval_obj.to_mesh()

    #     bm = bmesh.new()
    #     try:
    #         bm.from_mesh(mesh)
    #         bmesh.ops.triangulate(bm, faces=bm.faces)
    #         bm.verts.ensure_lookup_table()
    #         bm.faces.ensure_lookup_table()

    #         num_verts = len(bm.verts)
    #         num_faces = len(bm.faces)

    #         f.write(struct.pack("<I", num_verts))
    #         f.write(struct.pack("<I", num_faces))

    #         # -------------------------------------------------
    #         # 3. VERTICES (WORLD SPACE - Mafia X Z Y)
    #         # -------------------------------------------------
    #         min_b = [float('inf')] * 3
    #         max_b = [float('-inf')] * 3

    #         world_mat = obj.matrix_world

    #         for v in bm.verts:
    #             v_world = world_mat @ v.co
    #             vx, vy, vz = v_world.x, v_world.z, v_world.y

    #             f.write(struct.pack("<3f", vx, vy, vz))

    #             min_b[0] = min(min_b[0], vx)
    #             min_b[1] = min(min_b[1], vy)
    #             min_b[2] = min(min_b[2], vz)
    #             max_b[0] = max(max_b[0], vx)
    #             max_b[1] = max(max_b[1], vy)
    #             max_b[2] = max(max_b[2], vz)

    #         # -------------------------------------------------
    #         # 4. FACES (0,2,1 winding)
    #         # -------------------------------------------------
    #         for face in bm.faces:
    #             v = face.verts
    #             f.write(struct.pack("<3H", v[0].index, v[2].index, v[1].index))

    #     finally:
    #         bm.free()
    #         eval_obj.to_mesh_clear()

    #     # -------------------------------------------------
    #     # 5. BOUNDING BOX (AFTER FACES - v29)
    #     # -------------------------------------------------
    #     if num_verts > 0:
    #         f.write(struct.pack("<3f", *min_b))
    #         f.write(struct.pack("<3f", *max_b))
    #     else:
    #         f.write(struct.pack("<6f", 0, 0, 0, 0, 0, 0))

    #     # -------------------------------------------------
    #     # 6. PORTALS (INLINE SERIALIZATION)
    #     # -------------------------------------------------
    #     portals = []

    #     for child in obj.children:
    #         if (
    #             child.type == 'MESH'
    #             and int(getattr(child, "ls3d_frame_type", '1')) == FRAME_SECTOR
    #             and child.parent == obj
    #             and re.search(r"_portal\d+$", child.name, re.IGNORECASE)
    #         ):
    #             portals.append(child)

    #     portals.sort(key=lambda o: o.name)
    #     f.write(struct.pack("<B", len(portals)))

    #     for p_obj in portals:
    #         # -------------------------------------------------
    #         # PORTAL GEOMETRY
    #         # -------------------------------------------------
    #         verts, normal, center = self.get_ordered_portal_verts(p_obj)

    #         flags = getattr(p_obj, "ls3d_portal_flags", 0)
    #         near = getattr(p_obj, "ls3d_portal_near", 0.0)
    #         far  = getattr(p_obj, "ls3d_portal_far", 0.0)

    #         # Empty portal (still valid)
    #         if len(verts) < 3:
    #             f.write(struct.pack("<B", 0))
    #             f.write(struct.pack("<I", flags))
    #             f.write(struct.pack("<f", near))
    #             f.write(struct.pack("<f", far))
    #             f.write(struct.pack("<3f", 0.0, 0.0, 0.0))
    #             f.write(struct.pack("<f", 0.0))
    #             continue

    #         # -------------------------------------------------
    #         # TRANSFORM - Mafia Space (X, Z, Y)
    #         # -------------------------------------------------
    #         mafia_verts = [Vector((v.x, v.z, v.y)) for v in verts]
    #         mafia_normal = Vector((normal.x, normal.z, normal.y))
    #         mafia_point = mafia_verts[0]

    #         stored_normal = -mafia_normal
    #         stored_d = mafia_point.dot(mafia_normal)

    #         # -------------------------------------------------
    #         # WRITE PORTAL STRUCT
    #         # -------------------------------------------------
    #         f.write(struct.pack("<B", len(mafia_verts)))
    #         f.write(struct.pack("<I", flags))
    #         f.write(struct.pack("<f", near))
    #         f.write(struct.pack("<f", far))

    #         f.write(struct.pack(
    #             "<3f",
    #             stored_normal.x,
    #             stored_normal.y,
    #             stored_normal.z
    #         ))
    #         f.write(struct.pack("<f", stored_d))

    #         for v in mafia_verts:
    #             f.write(struct.pack("<3f", v.x, v.y, v.z))

    def get_tex(self, node, socket_name):
            """
            Helper to extract texture name and intensity from a specific socket 
            of the LS3D Material Node.
            """
            if not node or socket_name not in node.inputs:
                return "", 0.0
                
            socket = node.inputs[socket_name]
            if not socket.is_linked:
                return "", 0.0
                
            # Follow the link to find what is connected (Texture or Env Group)
            link = socket.links[0]
            from_node = link.from_node
            
            texture_name = ""
            intensity = 0.0
            
            # 1. Check for LS3D Environment Group (Used for Environment Maps)
            if from_node.type == 'GROUP' and from_node.node_tree and "LS3D Environment" in from_node.node_tree.name:
                # Get Intensity from the group input
                if "Intensity" in from_node.inputs:
                    # We assume a static value here, not a driven one
                    intensity = from_node.inputs["Intensity"].default_value
                    
                # Get Texture from the group's "Color" input
                if "Color" in from_node.inputs and from_node.inputs["Color"].is_linked:
                    # Dig deeper to find the actual image node connected to the group
                    inner_link = from_node.inputs["Color"].links[0]
                    tex_node = self.find_texture_node(inner_link.from_node)
                    if tex_node and tex_node.image:
                        texture_name = tex_node.image.name

            # 2. Standard connection (Direct Image Texture or via Math/Mix nodes)
            else:
                tex_node = self.find_texture_node(from_node)
                if tex_node and tex_node.image:
                    texture_name = tex_node.image.name
                    
            return texture_name, intensity

    def serialize_material(self, f, mat, mat_index):

        # -------------------------------------------------
        # 1. FLAGS (write as U32)
        # -------------------------------------------------
        flags_unsigned = mat.ls3d_material_flags & 0xFFFFFFFF
        f.write(struct.pack("<I", flags_unsigned))

        flags = flags_unsigned

        # -------------------------------------------------
        # 2. COLORS
        # -------------------------------------------------
        amb = getattr(mat, "ls3d_ambient_color",  (0.5, 0.5, 0.5))
        dif = getattr(mat, "ls3d_diffuse_color",  (1.0, 1.0, 1.0))
        emi = getattr(mat, "ls3d_emission_color", (0.0, 0.0, 0.0))

        # -------------------------------------------------
        # 3. TEXTURES + OPACITY
        # -------------------------------------------------
        opacity    = getattr(mat, "ls3d_opacity",    1.0)
        env_amount = getattr(mat, "ls3d_env_amount", 0.0)

        diff_img  = getattr(mat, "ls3d_diffuse_tex", None)
        alpha_img = getattr(mat, "ls3d_alpha_tex",   None)
        env_img   = getattr(mat, "ls3d_env_tex",     None)

        if diff_img:
            diff_tex = diff_img.name
        else:
            diff_tex = ""

        if alpha_img:
            alpha_tex = alpha_img.name
        else:
            alpha_tex = ""

        if env_img:
            env_tex = env_img.name
        else:
            env_tex = ""

        f.write(struct.pack("<3f", *amb))
        f.write(struct.pack("<3f", *dif))
        f.write(struct.pack("<3f", *emi))
        f.write(struct.pack("<f",  opacity))

        # -------------------------------------------------
        # 4. FLAG TESTS
        # -------------------------------------------------
        env_enabled    = (flags & MTL_ENV_ENABLE)    != 0
        alpha_enabled  = (flags & MTL_ALPHA_ENABLE)  != 0
        alpha_tex_flag = (flags & MTL_ALPHATEX)       != 0
        image_alpha    = (flags & MTL_ALPHA_IN_TEX)  != 0
        color_key      = (flags & MTL_ALPHA_COLORKEY) != 0
        additive       = (flags & MTL_ALPHA_ADDITIVE) != 0
        animated_diff  = (flags & MTL_DIFFUSE_ANIMATED) != 0

        # -------------------------------------------------
        # 5. ENVIRONMENT
        # -------------------------------------------------
        if env_enabled:
            f.write(struct.pack("<f", env_amount))
            self.write_string(f, env_tex.upper())

        # -------------------------------------------------
        # 6. DIFFUSE (ALWAYS write length byte)
        # -------------------------------------------------
        diffuse_count = self.write_string(f, diff_tex.upper())

        # -------------------------------------------------
        # 7. ALPHA (exact same condition as importer)
        # -------------------------------------------------
        if (
            diffuse_count > 0 and
            #alpha_enabled  and
            alpha_tex_flag and
            not image_alpha and
            not color_key  and
            not additive
        ):
            self.write_string(f, alpha_tex.upper())

        # -------------------------------------------------
        # 8. ANIMATION
        # -------------------------------------------------
        if animated_diff:
            f.write(struct.pack("<I", mat.ls3d_anim_frames))
            f.write(struct.pack("<H", 0))
            f.write(struct.pack("<I", mat.ls3d_anim_period))
            f.write(struct.pack("<I", 0))
            f.write(struct.pack("<I", 0))

    def serialize_object(self, f, obj, lods, armature=None):
        """Write the mesh geometry (object data block) for any visual type.

        When *armature* is given (SINGLEMESH / SINGLEMORPH) the vertices are
        sorted by bone group and per-LOD skin data is collected and returned
        as the third element.

        Returns
        -------
        (num_lods, all_lod_mappings)               — when armature is None
        (num_lods, all_lod_mappings, all_lod_skin)  — when armature is given
        """
        WEIGHT_THRESH = 1.0 - 1e-10
        SENTINEL      = 1e16

        # ── Armature / skin setup ─────────────────────────────────────────────
        joint_map = self.joint_maps.get(armature, {}) if armature else {}

        if armature:
            ordered_bones = sorted(
                [b for b in armature.data.bones
                 if not _is_blend_bone(b, armature)],
                key=lambda b: joint_map.get(b.name, float('inf'))
            )
            num_groups = len(ordered_bones)
            if obj.parent == armature:
                skin_mesh_world = obj.matrix_parent_inverse @ obj.matrix_basis
            else:
                skin_mesh_world = obj.matrix_world.copy()

        f.write(struct.pack("<H", 0))
        f.write(struct.pack("<B", len(lods)))

        # Non-armature: one depsgraph before the loop (matches original
        # serialize_object exactly).
        if not armature:
            depsgraph = bpy.context.evaluated_depsgraph_get()

        all_lod_mappings = []
        all_lod_skin     = [] if armature else None

        for lod_obj in lods:

            lod_dist = float(getattr(lod_obj, "ls3d_lod_dist", 0.0))
            f.write(struct.pack("<f", lod_dist))

            # ── Evaluate mesh ─────────────────────────────────────────────────
            if armature:
                # Armature path: switch to REST, get a *fresh* depsgraph so
                # Blender evaluates bind-pose geometry, then restore.
                arm_pose_saved = armature.data.pose_position
                armature.data.pose_position = 'REST'

                depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_obj  = lod_obj.evaluated_get(depsgraph)
                mesh      = eval_obj.to_mesh(preserve_all_data_layers=True,
                                             depsgraph=depsgraph)

                armature.data.pose_position = arm_pose_saved
            else:
                eval_obj = lod_obj.evaluated_get(depsgraph)
                mesh = eval_obj.to_mesh(
                    preserve_all_data_layers=True,
                    depsgraph=depsgraph
                )

            if not mesh:
                f.write(struct.pack("<H", 0))
                f.write(struct.pack("<B", 0))
                if armature:
                    eval_obj.to_mesh_clear()
                    all_lod_skin.append(None)
                all_lod_mappings.append({})
                continue

            mesh.calc_loop_triangles()
            uv_layer = mesh.uv_layers.active

            if armature:
                # ──────────────────────────────────────────────────────────────
                # SINGLEMESH path — dedup vertices, sort by bone group
                # (copied verbatim from the working serialize_singlemesh)
                # ──────────────────────────────────────────────────────────────
                unique_verts_map = {}
                temp_verts_list  = []
                tri_batch        = []
                used_slots       = set()

                for tri in mesh.loop_triangles:
                    used_slots.add(tri.material_index)
                    poly      = mesh.polygons[tri.polygon_index]
                    is_smooth = poly.use_smooth
                    tri_indices = []

                    for loop_index in tri.loops:
                        loop    = mesh.loops[loop_index]
                        orig_vi = loop.vertex_index

                        if uv_layer:
                            uv = uv_layer.data[loop_index].uv
                            u, v_val = uv.x, 1.0 - uv.y
                        else:
                            u, v_val = 0.0, 0.0

                        if is_smooth:
                            uq  = struct.unpack('f', struct.pack('f', u))[0]
                            vq  = struct.unpack('f', struct.pack('f', v_val))[0]
                            key = (orig_vi, uq, vq)
                        else:
                            key = (orig_vi, tri.polygon_index)

                        if key not in unique_verts_map:
                            idx = len(temp_verts_list)
                            unique_verts_map[key] = idx
                            co = mesh.vertices[orig_vi].co
                            no = loop.normal
                            temp_verts_list.append({'orig_vi': orig_vi, 'co': co, 'no': no, 'u': u, 'v': v_val})
                            tri_indices.append(idx)
                        else:
                            tri_indices.append(unique_verts_map[key])

                    tri_batch.append((tri.material_index, tri_indices))

                # Classify vertices by bone
                group_noW = [[] for _ in range(num_groups)]
                group_W   = [[] for _ in range(num_groups)]
                root_noW  = []

                for t_idx, v_data in enumerate(temp_verts_list):
                    orig_vi    = v_data['orig_vi']
                    vert       = mesh.vertices[orig_vi]
                    vert_bones = {}

                    for ge in vert.groups:
                        if ge.group >= len(lod_obj.vertex_groups): continue
                        vg_name = lod_obj.vertex_groups[ge.group].name
                        if vg_name in joint_map and ge.weight > 1e-10:
                            vert_bones[vg_name] = ge.weight

                    if not vert_bones:
                        root_noW.append(t_idx)
                        continue

                    target_bone_idx    = -1
                    target_weight_type = 'noW'
                    child_weight       = 0.0

                    if len(vert_bones) == 1:
                        bone_name, weight = next(iter(vert_bones.items()))
                        g = joint_map[bone_name] - 1
                        target_bone_idx = g
                        if weight >= WEIGHT_THRESH:
                            target_weight_type = 'noW'
                        else:
                            target_weight_type = 'W'
                            child_weight = weight
                    else:
                        child_name   = max(vert_bones, key=lambda n: joint_map.get(n, 0))
                        child_weight = vert_bones[child_name]
                        g = joint_map[child_name] - 1
                        target_bone_idx = g
                        if child_weight >= WEIGHT_THRESH:
                            target_weight_type = 'noW'
                        else:
                            target_weight_type = 'W'

                    if target_bone_idx < 0 or target_bone_idx >= num_groups:
                        root_noW.append(t_idx)
                    else:
                        if target_weight_type == 'noW':
                            group_noW[target_bone_idx].append(t_idx)
                        else:
                            group_W[target_bone_idx].append((t_idx, child_weight))

                # Build final sorted buffer
                final_verts_order = []
                for g in range(num_groups):
                    final_verts_order.extend(group_noW[g])
                    final_verts_order.extend([vi for vi, _ in group_W[g]])
                final_verts_order.extend(root_noW)

                temp_to_final = {old: new for new, old in enumerate(final_verts_order)}

                # Write geometry
                if len(final_verts_order) > 65535:
                    raise ValueError(
                        f"Mesh '{lod_obj.name}' has {len(final_verts_order)} unique vertices "
                        f"after UV/normal splitting, exceeding the 4DS limit of 65535. "
                        f"Reduce polygon count or merge UV islands."
                    )
                f.write(struct.pack("<H", len(final_verts_order)))

                r_min = [SENTINEL, SENTINEL, SENTINEL]
                r_max = [-SENTINEL, -SENTINEL, -SENTINEL]

                for t_idx in final_verts_order:
                    v          = temp_verts_list[t_idx]
                    px, py, pz = v['co'].x, v['co'].z, v['co'].y
                    nx, ny, nz = v['no'].x, v['no'].z, v['no'].y
                    f.write(struct.pack("<3f", px, py, pz))
                    f.write(struct.pack("<3f", nx, ny, nz))
                    f.write(struct.pack("<2f", v['u'], v['v']))
                    if px < r_min[0]: r_min[0] = px
                    if py < r_min[1]: r_min[1] = py
                    if pz < r_min[2]: r_min[2] = pz
                    if px > r_max[0]: r_max[0] = px
                    if py > r_max[1]: r_max[1] = py
                    if pz > r_max[2]: r_max[2] = pz

                if len(final_verts_order) == 0:
                    r_min = [0.0, 0.0, 0.0]
                    r_max = [0.0, 0.0, 0.0]

                used_slots_sorted = sorted(used_slots)
                f.write(struct.pack("<B", len(used_slots_sorted)))

                for mat_slot in used_slots_sorted:
                    faces = [tris for m, tris in tri_batch if m == mat_slot]
                    f.write(struct.pack("<H", len(faces)))
                    for idxs in faces:
                        i0 = temp_to_final[idxs[0]]
                        i1 = temp_to_final[idxs[1]]
                        i2 = temp_to_final[idxs[2]]
                        f.write(struct.pack("<3H", i0, i2, i1))
                    mat_id = 0
                    if 0 <= mat_slot < len(lod_obj.material_slots):
                        mat = lod_obj.material_slots[mat_slot].material
                        if mat and mat in self.materials:
                            mat_id = self.materials.index(mat) + 1
                    f.write(struct.pack("<H", mat_id))

                mapping = {}
                for t_idx in final_verts_order:
                    orig     = temp_verts_list[t_idx]['orig_vi']
                    final_id = temp_to_final[t_idx]
                    if orig not in mapping: mapping[orig] = []
                    mapping[orig].append(final_id)
                all_lod_mappings.append(mapping)

                # Collect skin data (written later by serialize_singlemesh)
                # Use precomputed bone_full_world for inv_bind.
                groups_data = []
                for g_idx, bone in enumerate(ordered_bones):

                    bone_world_full = self.bone_full_world.get(
                        (armature, bone.name))
                    if bone_world_full is not None:
                        inv_bind = bone_world_full.inverted() @ skin_mesh_world
                    else:
                        inv_bind = bone.matrix_local.inverted() @ skin_mesh_world

                    nw_vis       = group_noW[g_idx]
                    w_list       = group_W[g_idx]
                    all_vis_temp = nw_vis + [x[0] for x in w_list]

                    if all_vis_temp:
                        b_min = [SENTINEL, SENTINEL, SENTINEL]
                        b_max = [-SENTINEL, -SENTINEL, -SENTINEL]
                        for t_idx in all_vis_temp:
                            co_bl   = temp_verts_list[t_idx]['co']
                            co_bone = inv_bind @ Vector((co_bl.x, co_bl.y, co_bl.z, 1.0))
                            bx, by, bz = co_bone.x, co_bone.z, co_bone.y
                            if bx < b_min[0]: b_min[0] = bx
                            if by < b_min[1]: b_min[1] = by
                            if bz < b_min[2]: b_min[2] = bz
                            if bx > b_max[0]: b_max[0] = bx
                            if by > b_max[1]: b_max[1] = by
                            if bz > b_max[2]: b_max[2] = bz
                    else:
                        b_min = [0.0, 0.0, 0.0]
                        b_max = [0.0, 0.0, 0.0]

                    bp = bone.parent
                    if bp and _is_blend_bone(bp, armature):
                        bp = None
                    par = joint_map[bp.name] if bp else 0

                    groups_data.append({
                        'noW':      len(nw_vis),
                        'W':        len(w_list),
                        'par':      par,
                        'b_min':    tuple(b_min),
                        'b_max':    tuple(b_max),
                        'weights':  [x[1] for x in w_list],
                        'inv_bind': inv_bind
                    })

                all_lod_skin.append({
                    'num_groups': num_groups,
                    'root_noW':   len(root_noW),
                    'r_min':      tuple(r_min),
                    'r_max':      tuple(r_max),
                    'groups':     groups_data
                })

                eval_obj.to_mesh_clear()

            else:
                # ──────────────────────────────────────────────────────────────
                # VISUAL_OBJECT path — pre-allocation vertex buffer
                # (copied verbatim from the working serialize_object)
                # ──────────────────────────────────────────────────────────────
                tri_batch  = []
                used_slots = set()

                vertex_buffer = []
                mapping       = {}
                flat_versions = {}
                smooth_uv_idx = {}
                smooth_seen   = set()

                for v in mesh.vertices:
                    co = v.co
                    vertex_buffer.append([co.x, co.y, co.z, 0.0, 0.0, 0.0, 0.0, 0.0])
                    mapping[v.index] = [v.index]

                for tri in mesh.loop_triangles:
                    used_slots.add(tri.material_index)
                    poly      = mesh.polygons[tri.polygon_index]
                    is_smooth = poly.use_smooth
                    tri_indices = []

                    for loop_index in tri.loops:
                        loop    = mesh.loops[loop_index]
                        orig_vi = loop.vertex_index
                        no      = loop.normal

                        if uv_layer:
                            uv    = uv_layer.data[loop_index].uv
                            u     = uv.x
                            v_val = 1.0 - uv.y
                        else:
                            u     = 0.0
                            v_val = 0.0

                        if is_smooth:
                            uq = struct.unpack('f', struct.pack('f', u))[0]
                            vq = struct.unpack('f', struct.pack('f', v_val))[0]
                            uv_key = (orig_vi, uq, vq)
                            if uv_key in smooth_uv_idx:
                                buf_idx = smooth_uv_idx[uv_key]
                                vertex_buffer[buf_idx][3:8] = [no.x, no.y, no.z, u, v_val]
                            elif orig_vi not in smooth_seen:
                                smooth_seen.add(orig_vi)
                                smooth_uv_idx[uv_key] = orig_vi
                                vertex_buffer[orig_vi][3:8] = [no.x, no.y, no.z, u, v_val]
                                buf_idx = orig_vi
                            else:
                                co      = mesh.vertices[orig_vi].co
                                buf_idx = len(vertex_buffer)
                                vertex_buffer.append([co.x, co.y, co.z, no.x, no.y, no.z, u, v_val])
                                smooth_uv_idx[uv_key] = buf_idx
                                mapping[orig_vi].append(buf_idx)
                            tri_indices.append(buf_idx)
                        else:
                            key = (orig_vi, tri.polygon_index)
                            if key in flat_versions:
                                tri_indices.append(flat_versions[key])
                            else:
                                co      = mesh.vertices[orig_vi].co
                                new_idx = len(vertex_buffer)
                                vertex_buffer.append([co.x, co.y, co.z, no.x, no.y, no.z, u, v_val])
                                flat_versions[key] = new_idx
                                mapping[orig_vi].append(new_idx)
                                tri_indices.append(new_idx)

                    tri_batch.append((tri.material_index, tri_indices))

                # Write vertex buffer
                if len(vertex_buffer) > 65535:
                    raise ValueError(
                        f"Mesh '{lod_obj.name}' has {len(vertex_buffer)} unique vertices "
                        f"after normal splitting, exceeding the 4DS limit of 65535. "
                        f"Reduce polygon count."
                    )
                f.write(struct.pack("<H", len(vertex_buffer)))

                for px, py, pz, nx, ny, nz, u, v in vertex_buffer:
                    f.write(struct.pack("<3f", px, pz, py))   # Y↔Z swap
                    f.write(struct.pack("<3f", nx, nz, ny))
                    f.write(struct.pack("<2f", u, v))

                # Write material groups
                used_slots_sorted = sorted(used_slots)
                f.write(struct.pack("<B", len(used_slots_sorted)))

                for mat_slot in used_slots_sorted:
                    faces = [idxs for m, idxs in tri_batch if m == mat_slot]
                    f.write(struct.pack("<H", len(faces)))

                    for i0, i1, i2 in faces:
                        f.write(struct.pack("<3H", i0, i2, i1))  # reverse winding

                    mat_id = 0
                    if 0 <= mat_slot < len(lod_obj.material_slots):
                        mat = lod_obj.material_slots[mat_slot].material
                        if mat and mat in self.materials:
                            mat_id = self.materials.index(mat) + 1
                    f.write(struct.pack("<H", mat_id))

                eval_obj.to_mesh_clear()
                all_lod_mappings.append(mapping)

        if armature:
            return len(lods), all_lod_mappings, all_lod_skin
        return len(lods), all_lod_mappings

    def validate_billboard(self, obj):
        """
        BILLBOARD (VISUAL_BILLBOARD):
        - Back faces should look towards the object's local Y+.
          Uses poly.normal.y (local-space face normal Y component) so it works
          correctly for both flat planes and 3D meshes.
            avg Y < 0 -> fronts face local -Y -> backs toward +Y -> correct
            avg Y >= 0 -> fronts face local +Y -> backs toward -Y -> warn
        """
        mesh = obj.data
        if not mesh or not mesh.polygons:
            return

        avg_y = sum(p.normal.y for p in mesh.polygons) / len(mesh.polygons)

        # Front normals toward local +Y means back faces toward local -Y -> wrong
        if avg_y >= 0.0:
            log_warn(
                f"Billboard '{obj.name}': back faces do not point towards Y+. "
                "It may not be visible in game. "
                "Flip normals or rotate the mesh 180° on the X axis."
            )

    def serialize_billboard(self, f, obj):
            mode_prop = getattr(obj, "rot_mode", '1')
            
            if mode_prop == '1':
                mafia_axis = 0
                axis_mode = 0
            else:
                axis_mode = 1
                axis_prop = getattr(obj, "rot_axis", '2')
                if axis_prop == '1':
                    mafia_axis = 0  # X
                elif axis_prop == '2':
                    mafia_axis = 1  # Blender Z (up) -> Mafia Y (up)
                elif axis_prop == '3':
                    mafia_axis = 2  # Blender Y -> Mafia Z
                else:
                    mafia_axis = 1  # Default to Mafia Y
            
            f.write(struct.pack("<I", mafia_axis))
            f.write(struct.pack("<?", bool(axis_mode)))

    def serialize_mirror(self, f, obj):
        """
        Mafia v29 mirror export.
        """

        # -------------------------------------------------
        # 1. VIEWBOX (already validated & skipped as frame)
        # -------------------------------------------------
        viewbox = next(
            c for c in obj.children
            if c.name.lower().endswith("_viewbox")
        )

        # -------------------------------------------------
        # 2. EVALUATED MESH
        # -------------------------------------------------
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces)

        try:
            # -------------------------------------------------
            # 3. BOUNDS (LOCAL SPACE)
            # -------------------------------------------------
            if bm.verts:
                min_b = Vector((
                    min(v.co.x for v in bm.verts),
                    min(v.co.y for v in bm.verts),
                    min(v.co.z for v in bm.verts),
                ))
                max_b = Vector((
                    max(v.co.x for v in bm.verts),
                    max(v.co.y for v in bm.verts),
                    max(v.co.z for v in bm.verts),
                ))
            else:
                min_b = Vector((0, 0, 0))
                max_b = Vector((0, 0, 0))

            # dmin / dmax (X, Z, Y)
            f.write(struct.pack("<3f", min_b.x, min_b.z, min_b.y))
            f.write(struct.pack("<3f", max_b.x, max_b.z, max_b.y))

            # -------------------------------------------------
            # 4. CENTER + RADIUS
            # -------------------------------------------------
            center = (min_b + max_b) * 0.5
            radius = (max_b - min_b).length * 0.5

            f.write(struct.pack("<3f", center.x, center.z, center.y))
            f.write(struct.pack("<f", radius))

            # -------------------------------------------------
            # 5. VIEWBOX MATRIX
            # -------------------------------------------------
            m = viewbox.matrix_local

            # Row 0
            f.write(struct.pack("<4f", m[0][0], m[2][0], m[1][0], 0.0))
            # Row 1 (Up)
            f.write(struct.pack("<4f", m[0][2], m[2][2], m[1][2], 0.0))
            # Row 2 (Forward)
            f.write(struct.pack("<4f", m[0][1], m[2][1], m[1][1], 0.0))
            # Row 3 (Position)
            f.write(struct.pack("<4f", m[0][3], m[2][3], m[1][3], 1.0))

            # -------------------------------------------------
            # 6. COLOR + RANGE
            # -------------------------------------------------
            color = getattr(obj, "ls3d_mirror_color", (1.0, 1.0, 1.0))
            f.write(struct.pack("<3f", *color))

            rng = float(getattr(obj, "ls3d_mirror_range", 50.0))
            f.write(struct.pack("<f", rng))

            # -------------------------------------------------
            # 7. GEOMETRY (TRIMESH)
            # -------------------------------------------------
            f.write(struct.pack("<I", len(bm.verts)))
            f.write(struct.pack("<I", len(bm.faces)))

            for v in bm.verts:
                f.write(struct.pack("<3f", v.co.x, v.co.z, v.co.y))

            for face in bm.faces:
                v = face.verts
                f.write(struct.pack("<3H", v[0].index, v[2].index, v[1].index))

        finally:
            bm.free()
            eval_obj.to_mesh_clear()

    def serialize_lensflare(self, f, obj):
        """
        Serialize Mafia lens flare (VISUAL_LENSFLARE).
        Payload format (v29):
            U8  glow_count
            repeat:
                F32 position
                U16 material_index_minus_1
        """

        # -------------------------------------------------
        # Collect glow data from object
        # -------------------------------------------------

        glow_position = getattr(obj, "ls3d_glow_position", 0.0)
        glow_material = getattr(obj, "ls3d_glow_material", None)

        # -------------------------------------------------
        # Resolve material index (0-based in file)
        # -------------------------------------------------

        mat_index = 0

        if glow_material and glow_material in self.materials:
            mat_index = self.materials.index(glow_material) + 1
        else:
            # Mafia crashes if matId <= 0 (after +1)
            # So we must ensure at least 0 in file means matId 1 internally.
            mat_index = 0

        # -------------------------------------------------
        # Write Glow Count (Mafia usually uses 1)
        # -------------------------------------------------

        f.write(struct.pack("<B", 1))  # one glow

        # -------------------------------------------------
        # Write Glow Entry
        # -------------------------------------------------

        f.write(struct.pack("<f", float(glow_position)))
        f.write(struct.pack("<H", mat_index))

    def collect_lods(self):
            self.lod_map = {}
            all_lod_objects = set()
            
            base_objects = [o for o in self.objects_to_export if o.type == "MESH" and "_lod" not in o.name]
            scene_objects = bpy.context.scene.objects
            
            for base_obj in base_objects:
                self.lod_map[base_obj] = [base_obj]
                base_name = base_obj.name
                
                for i in range(1, 10): 
                    target_name = f"{base_name}_lod{i}"
                    
                    if target_name in scene_objects:
                        found_lod = scene_objects[target_name]
                        if found_lod.type == "MESH":
                            while len(self.lod_map[base_obj]) <= i:
                                self.lod_map[base_obj].append(None)
                            
                            self.lod_map[base_obj][i] = found_lod
                            all_lod_objects.add(found_lod)
                
                self.lod_map[base_obj] = [x for x in self.lod_map[base_obj] if x is not None]

            return all_lod_objects
        
    def prepare_for_export(self):
        # ── Force REST position and disable ALL animation during export ───
        # The 4DS file stores rest-pose transforms.  When a 5DS animation is
        # loaded, both pose-bone keyframes *and* object-level keyframes (on the
        # armature and skinned mesh) shift matrix_world.  We must neutralise
        # everything so the export sees the un-animated rest state.
        saved_pose_positions = {}
        saved_influences = {}  # obj → original action_influence

        # 1. Armatures → REST pose
        for obj in self.objects_to_export:
            if obj.type == 'ARMATURE':
                saved_pose_positions[obj] = obj.data.pose_position
                obj.data.pose_position = 'REST'

        # 2. Zero out action_influence on EVERY scene object that has animation
        #    data.  This disables object-level animation (location / rotation /
        #    scale keyframes) without detaching or destroying the action.
        for obj in bpy.context.scene.objects:
            ad = obj.animation_data
            if ad and ad.action:
                saved_influences[obj] = ad.action_influence
                ad.action_influence = 0.0

        if saved_pose_positions or saved_influences:
            bpy.context.view_layer.update()

        try:
            return self.serialize_file()
        finally:
            # ── Restore everything ─────────────────────────────────────────
            for obj, pos in saved_pose_positions.items():
                obj.data.pose_position = pos
            for obj, infl in saved_influences.items():
                if obj.animation_data:
                    obj.animation_data.action_influence = infl
            if saved_pose_positions or saved_influences:
                bpy.context.view_layer.update()

    def serialize_file(self):
        with open(self.filepath, "wb") as f:
            self.serialize_header(f)
            self.progress(5)

            self.materials = self.collect_materials()
            log_info(f"Materials: {len(self.materials)}")
            f.write(struct.pack("<H", len(self.materials)))
            for i, mat in enumerate(self.materials):
                self.serialize_material(f, mat, i)
            self.progress(10)

            lod_objects_set = self.collect_lods()

            # Portal meshes are written as children of their sector, not as
            # top-level frames. Keep the same detection logic as before.
            portal_objects = set()
            for obj in self.objects_to_export:
                if (
                    obj.type == 'MESH'
                    and int(getattr(obj, "ls3d_frame_type", '1')) == FRAME_SECTOR
                    and obj.parent
                    and int(getattr(obj.parent, "ls3d_frame_type", '1')) == FRAME_SECTOR
                    and re.search(r"_portal\d+$", obj.name, re.IGNORECASE)
                ):
                    portal_objects.add(obj)

            # Mirror viewboxes are part of the mirror payload, not separate frames.
            # Use the EXACT same conditions here AND in serialize_frame's guard so
            # the counted-vs-written frame numbers always match.
            mirror_viewboxes = set()
            for obj in self.objects_to_export:
                if (
                    obj.type == 'EMPTY'
                    and obj.empty_display_type == 'CUBE'
                    and int(getattr(obj, "ls3d_frame_type", FRAME_DUMMY)) == FRAME_DUMMY
                    and obj.name.lower().endswith("_viewbox")
                    and obj.parent
                    and hasattr(obj.parent, "visual_type")
                    and int(getattr(obj.parent, "visual_type", -1)) == VISUAL_MIRROR
                ):
                    mirror_viewboxes.add(obj)

            scene_names = set(o.name for o in bpy.context.scene.objects)
            raw_objects = [
                obj for obj in self.objects_to_export
                if obj.name in scene_names
                and obj not in lod_objects_set
                and obj not in portal_objects
                and obj not in mirror_viewboxes
                and obj.type in ("MESH", "EMPTY", "ARMATURE")
            ]

            # Build write-order: parents before children.
            self.objects = []
            roots = [o for o in raw_objects if (not o.parent) or (o.parent not in raw_objects)]

            def sort_hierarchy(obj):
                if obj in self.objects:
                    return
                self.objects.append(obj)
                for child in sorted(
                    [c for c in obj.children if c in raw_objects],
                    key=lambda o: o.name
                ):
                    sort_hierarchy(child)

            for root in sorted(roots, key=lambda o: o.name):
                sort_hierarchy(root)
            for o in raw_objects:
                if o not in self.objects:
                    self.objects.append(o)

            # SINGLEMESH/SINGLEMORPH frames must precede their armature's FRAME_JOINT
            # bones in the file. The game expects the skin mesh before the bones that
            # deform it. Placing skin meshes first also gives them parent_id = 0
            # naturally, because the armature hasn't been registered yet.
            def is_skin_mesh(o):
                if o.type != 'MESH':
                    return False
                if int(getattr(o, 'ls3d_frame_type', FRAME_VISUAL)) != FRAME_VISUAL:
                    return False
                return int(getattr(o, 'visual_type', 0)) in (VISUAL_SINGLEMESH, VISUAL_SINGLEMORPH)

            # Build pairs: each skin mesh immediately followed by its armature.
            # The 4DS format expects the base object (SINGLEMESH/SINGLEMORPH)
            # right before the FRAME_JOINT bones that deform it.
            armatures    = [o for o in self.objects if o.type == 'ARMATURE']
            skin_meshes  = [o for o in self.objects if is_skin_mesh(o)]
            other_frames = [o for o in self.objects if not is_skin_mesh(o) and o.type != 'ARMATURE']

            # 4DS supports exactly one SINGLEMESH/SINGLEMORPH and one armature.
            if len(skin_meshes) > 1:
                names = ', '.join(f"'{o.name}'" for o in skin_meshes)
                self.add_error(f"Only one SingleMesh/SingleMorph allowed per 4DS file, found {len(skin_meshes)}: {names}")
                _add_fix("Remove or reparent extra skinned meshes — only one per 4DS file.")
            if len(armatures) > 1:
                names = ', '.join(f"'{o.name}'" for o in armatures)
                self.add_error(f"Only one Armature allowed per 4DS file, found {len(armatures)}: {names}")
                _add_fix("Remove extra armatures — only one allowed per 4DS file.")
            self.raise_if_errors()

            # Map each armature to its base object (already validated: exactly one)
            arm_to_skin = {}
            for o in self.objects:
                if is_skin_mesh(o) and o.parent and o.parent.type == 'ARMATURE':
                    arm_to_skin[o.parent] = o

            paired = []
            for arm in armatures:
                skin = arm_to_skin.get(arm)
                if skin:
                    paired.append(skin)
                paired.append(arm)

            self.objects = paired + other_frames

            # Frame count: armatures contribute one frame per bone (FRAME_JOINT),
            # all other objects contribute exactly one frame each.
            # Blend bones are excluded — they are not FRAME_JOINTs.
            visual_frames_count = sum(
                sum(1 for b in o.data.bones if not _is_blend_bone(b, o))
                if o.type == 'ARMATURE' else 1
                for o in self.objects
            )
            log_info(f"Frames: {visual_frames_count}")
            f.write(struct.pack("<H", visual_frames_count))

            self.frame_index = 1
            self.frames_map  = {}
            self.joint_maps  = {}  # armature_obj → {bone_name: 1-based index}

            # ── Pre-assign ALL frame IDs before writing any frame data ────────
            # DFS order — MUST match the traversal in serialize_joints exactly,
            # otherwise parent_frame_id values in the exported file are wrong.
            # Bone keys are namespaced by armature name to avoid collisions
            # when multiple armatures share bone names.
            for obj in self.objects:
                if obj.type == 'ARMATURE':
                    roots_b = sorted(
                        [b for b in obj.data.bones
                         if not _is_blend_bone(b, obj)
                         and (b.parent is None or _is_blend_bone(b.parent, obj))],
                        key=lambda b: b.name
                    )
                    stack = list(reversed(roots_b))
                    while stack:
                        bone = stack.pop()
                        self.frames_map[(obj, bone.name)] = self.frame_index
                        self.frame_index += 1
                        stack.extend(reversed(sorted(
                            [c for c in bone.children if not _is_blend_bone(c, obj)],
                            key=lambda b: b.name)))
                else:
                    self.frames_map[obj] = self.frame_index
                    self.frame_index += 1

            # Reset counter: serialize_frame / serialize_joints will advance it
            # in lockstep with the frames_map entries as they write each frame.
            self.frame_index = 1

            # Pre-populate joint_maps (per-armature) so serialize_singlemesh
            # can resolve vertex-group → bone-group index before joints are
            # written.  Must use the same alphabetical DFS as serialize_joints
            # so that the sequential IDs match the order bones are written.
            for obj in self.objects:
                if obj.type != 'ARMATURE':
                    continue
                arm_map = {}
                roots_b = sorted(
                    [b for b in obj.data.bones
                     if not _is_blend_bone(b, obj)
                     and (b.parent is None or _is_blend_bone(b.parent, obj))],
                    key=lambda b: b.name
                )
                stack = list(reversed(roots_b))
                idx   = 1
                while stack:
                    bone = stack.pop()
                    arm_map[bone.name] = idx
                    idx += 1
                    stack.extend(reversed(sorted(
                        [c for c in bone.children if not _is_blend_bone(c, obj)],
                        key=lambda b: b.name)))
                self.joint_maps[obj] = arm_map

            # ── Pre-compute bone_full_world for every bone in every armature ──
            # The 4DS game engine accumulates T@R@S from parent to child,
            # where T, R, S are the file-local transforms.  Blender bones are at
            # NOSCALE positions (T@R chain, no scale), so the full-scale world
            # position differs from the Blender bone position when ancestors have
            # non-unit ls3d_joint_scale.  Both serialize_joints (for inv_bind in
            # FRAME_JOINT body) and serialize_frame (for bone-parented children)
            # need the correct full-scale world matrix.
            self.bone_full_world = {}  # (armature_obj, bone_name) → Matrix 4×4

            for arm_obj in [o for o in self.objects if o.type == 'ARMATURE']:
                # Use bone.matrix_local directly — it is edit-bone rest data,
                # NEVER affected by animation.  Do NOT use arm_obj.matrix_world.

                # Find associated skin mesh
                skin_obj = None
                for candidate in self.objects:
                    vt = int(getattr(candidate, 'visual_type', -1))
                    if vt not in (VISUAL_SINGLEMESH, VISUAL_SINGLEMORPH):
                        continue
                    if (candidate.parent == arm_obj or
                        any(m.type == 'ARMATURE' and m.object == arm_obj
                            for m in candidate.modifiers)):
                        skin_obj = candidate
                        break

                # Skin mesh transform in armature-local space (animation-immune)
                if skin_obj and skin_obj.parent == arm_obj:
                    skin_local = skin_obj.matrix_parent_inverse @ skin_obj.matrix_basis
                elif skin_obj:
                    skin_local = skin_obj.matrix_world.copy()
                else:
                    skin_local = Matrix.Identity(4)
                sw_loc, sw_rot, _ = skin_local.decompose()

                # DFS — same order as serialize_joints / joint_maps
                roots_b = sorted(
                    [b for b in arm_obj.data.bones
                     if not _is_blend_bone(b, arm_obj)
                     and (b.parent is None or _is_blend_bone(b.parent, arm_obj))],
                    key=lambda b: b.name
                )
                ordered = []
                stack = list(reversed(roots_b))
                while stack:
                    bone = stack.pop()
                    ordered.append(bone)
                    stack.extend(reversed(sorted(
                        [c for c in bone.children if not _is_blend_bone(c, arm_obj)],
                        key=lambda b: b.name)))

                for bone in ordered:
                    # bone.matrix_local = noscale rest transform in armature space
                    bw_loc, bw_rot, _ = bone.matrix_local.decompose()

                    parent_bone = bone.parent
                    if parent_bone and _is_blend_bone(parent_bone, arm_obj):
                        parent_bone = None

                    if parent_bone:
                        pw_loc, pw_rot, _ = parent_bone.matrix_local.decompose()
                        file_pos = pw_rot.to_matrix().inverted() @ (bw_loc - pw_loc)
                        file_rot = pw_rot.inverted() @ bw_rot
                    else:
                        file_pos = sw_rot.to_matrix().inverted() @ (bw_loc - sw_loc)
                        file_rot = sw_rot.inverted() @ bw_rot

                    pb = arm_obj.pose.bones.get(bone.name)
                    file_scl = Vector(pb.get("ls3d_joint_scale", (1, 1, 1))) if pb else Vector((1, 1, 1))

                    local_trs = Matrix.LocRotScale(file_pos, file_rot, file_scl)

                    if parent_bone:
                        parent_full = self.bone_full_world.get(
                            (arm_obj, parent_bone.name), skin_local)
                    else:
                        parent_full = skin_local

                    self.bone_full_world[(arm_obj, bone.name)] = parent_full @ local_trs

            # ── Pre-validate all objects ───────────────────────────────────
            for obj in self.objects:
                if obj.type == 'ARMATURE':
                    self.validate_armature(obj)
            self.raise_if_errors()
            self.progress(25)

            # ── Write all frames — everything goes through serialize_frame ────
            total_objs = len(self.objects)
            for obj_i, obj in enumerate(self.objects):
                self.serialize_frame(f, obj)
                self.progress(25 + int(70 * (obj_i + 1) / max(total_objs, 1)))

            anim_count = int(getattr(bpy.context.scene, "ls3d_animated_object_count", 0)) & 0xFF
            f.write(struct.pack("<B", anim_count))
            self.progress(100)

        return self.filepath

class The4DSImporter:
    def __init__(self, filepath):
        self.filepath = filepath
        self.texture_cache = {}
        
        # Access the preferences strictly using the module name
        addon_prefs = bpy.context.preferences.addons.get(__name__)
        
        if addon_prefs:
            self.maps_dir = addon_prefs.preferences.textures_path
        else:
            self.maps_dir = None
            
        if not self.maps_dir or not os.path.exists(self.maps_dir):
            log_warn(f"Texture path invalid: {self.maps_dir}")
            self.maps_dir = None

        self.version = 0
        self.materials = []
        self.skinned_meshes = []
        self.frames_map = {}
        self.frame_index = 1
        self.joints = []
        self.bone_nodes = {}
        self.blend_bone_name = None
        self.bones_map = {}
        self.armature = None
        self.parenting_info = []
        self.frame_types = {}
        self.frame_matrices = {}
        self.frame_transforms = {}
        self.mafia_raw_transforms = {}
        self.bone_world_matrices = {}

    def get_or_load_texture(self, filename):
        if not self.maps_dir or not os.path.isdir(self.maps_dir):
            return None

        key = os.path.basename(filename).lower()

        # Cache hit
        if key in self.texture_cache:
            return self.texture_cache[key]

        # Fast path: exact filename
        path = os.path.join(self.maps_dir, key)
        if not os.path.exists(path):
            # Slow path: case-insensitive search
            try:
                for name in os.listdir(self.maps_dir):
                    if name.lower() == key:
                        path = os.path.join(self.maps_dir, name)
                        break
                else:
                    path = None
            except OSError:
                path = None

        if not path:
            self.texture_cache[key] = None
            return None

        try:
            image = bpy.data.images.load(path, check_existing=True)
        except Exception:
            image = None

        self.texture_cache[key] = image
        return image

    # --- MAIN IMPORT LOOP WITH LOGGING ---
    def import_file(self):
        filename = os.path.basename(self.filepath)
        
        # Initial Console Log
        print("\n" + "="*60)
        print(f"LS3D IMPORT STARTED: {filename}")
        print("="*60)

        # Setup Progress Bar
        wm = bpy.context.window_manager
        wm.progress_begin(0, 100)
        
        # Change Cursor to Wait
        bpy.context.window.cursor_set("WAIT")

        try:
            with open(self.filepath, "rb") as f:
                # 1. Header
                header = f.read(4)
                if header != b"4DS\0":
                    print("Error: Not a valid 4DS file (invalid header)")
                    log_error("Not a valid 4DS file (invalid header)")
                    return

                self.version = struct.unpack("<H", f.read(2))[0]
                if self.version != 29: # VERSION_MAFIA
                    print(f"Error: Unsupported 4DS version {self.version}. Only version 29 is supported.")
                    log_error(f"Unsupported 4DS version {self.version}")
                    return
                
                f.read(8) # Skip Time

                # 2. Materials
                mat_count = struct.unpack("<H", f.read(2))[0]
                log_info(f"Materials: {mat_count}")
                print(f"--- READING MATERIALS ({mat_count}) ---")
                
                self.materials = [None]
                for i in range(mat_count):
                    # Update Progress (First 30% of bar is materials)
                    wm.progress_update((i / mat_count) * 30)
                    
                    try:
                        mat = self.deserialize_material(f, i + 1)
                        self.materials.append(mat)
                        
                        # LOGGING: Material Name and Flags
                        unsigned_flags = mat.ls3d_material_flags & 0xFFFFFFFF
                        print(f"  [Mat {i+1:03d}/{mat_count}] '{mat.name}' | Flags: {hex(unsigned_flags)}")
                        
                    except Exception as e:
                        print(f"  [Mat {i+1:03d}] ERROR: {e}")
                        log_warn(f"Material {i+1}: {e}")
                        # Append dummy to keep index alignment
                        self.materials.append(bpy.data.materials.new(f"Error_Mat_{i}"))

                # 3. Frames
                frame_count = struct.unpack("<H", f.read(2))[0]
                log_info(f"Frames: {frame_count}")
                print(f"--- READING FRAMES ({frame_count}) ---")
                
                frames = []
                for i in range(frame_count):
                    # Update Progress (Remaining 70% of bar)
                    wm.progress_update(30 + ((i / frame_count) * 70))
                    
                    # LOGGING: Frame Index
                    print(f"  [Frame {i+1:03d}/{frame_count}] Processing...")
                    
                    if not self.deserialize_frame(f, self.materials, frames):
                        print(f"    !!! Failed to deserialize frame {i+1} !!!")
                        log_warn(f"Frame {i+1}: deserialization failed")
                        continue

                # 4. Post Processing
                print("--- POST PROCESSING ---")

                # FIX: Check self.joints instead of self.skinned_meshes
                # This ensures armature is built even if no skin mesh exists (e.g. animation files)
                if self.joints:
                    log_info(f"Building armature ({len(self.joints)} joints)")
                    print("  > Building armature...")
                    self.build_armature()

                log_info("Applying hierarchy")
                self.apply_deferred_parenting()

                if self.skinned_meshes:
                    log_info(f"Applying skinning ({len(self.skinned_meshes)} mesh(es))")
                    for mesh_obj, weights, _, is_primary in self.skinned_meshes:
                        self.apply_skinning(mesh_obj, weights, reparent=is_primary)

                log_info("Resolving target links")
                self.resolve_target_links(frames)

                # Check Animated object count
                try:
                    f.seek(-1, 2)
                    last_byte = f.read(1)
                    if last_byte:
                        anim_count = struct.unpack("<B", last_byte)[0]
                        bpy.context.scene.ls3d_animated_object_count = anim_count
                        log_info(f"Animated object count: {anim_count}")
                except Exception as e:
                    log_warn(f"Reading animated object count: {e}")
                    print(f"  > Warning reading animated object count: {e}")

                
                print(f"Import completed successfully: {filename}")

        except Exception as e:
            log_error(f"Critical error: {e}")
            print(f"\nCRITICAL IMPORT ERROR: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # Cleanup UI state even if error occurs
            print("="*60)
            wm.progress_end()
            bpy.context.window.cursor_set("DEFAULT")

    def read_string(self, f):
        # Read 1 byte for length
        length_byte = f.read(1)
        if not length_byte: return ""
        length = struct.unpack("B", length_byte)[0]
        
        if length == 0: return ""
        
        # Read string bytes
        bytes_data = f.read(length)
        
        # Decode as Windows-1250 (Standard for Mafia) to preserve accents
        return bytes_data.decode("windows-1250", errors="replace")
    
    def set_material_data(
        self, material, diffuse, alpha_tex, env_tex, emission, opacity, env_amount, use_color_key
    ):
        def load(name):
            return self.get_or_load_texture(name) if name else None

        material.ls3d_opacity    = opacity
        material.ls3d_env_amount = env_amount

        if use_color_key:
            material.ls3d_flag_alpha_colorkey = True
            # Read key color directly from disk NOW while we have the absolute path
            if diffuse and self.maps_dir:
                basename = os.path.basename(diffuse.lower())
                abs_path = os.path.join(self.maps_dir, basename)
                if not os.path.isfile(abs_path):
                    try:
                        for name in os.listdir(self.maps_dir):
                            if name.lower() == basename:
                                abs_path = os.path.join(self.maps_dir, name)
                                break
                        else:
                            abs_path = None
                    except:
                        abs_path = None
                if abs_path:
                    try:
                        with open(abs_path, 'rb') as f:
                            data = f.read()
                        if data[0:2] == b'BM':
                            dib_size  = int.from_bytes(data[14:18], 'little')
                            bit_depth = int.from_bytes(data[28:30], 'little')
                            if bit_depth in (1, 4, 8):
                                b, g, r, _ = data[14 + dib_size : 18 + dib_size]
                                material.ls3d_color_key = (
                                    _srgb_to_linear(r / 255.0),
                                    _srgb_to_linear(g / 255.0),
                                    _srgb_to_linear(b / 255.0),
                                )
                    except Exception as e:
                        print(f"LS3D: color key read failed for {diffuse}: {e}")

        material.ls3d_diffuse_tex = load(diffuse)
        material.ls3d_alpha_tex   = load(alpha_tex)
        material.ls3d_env_tex     = load(env_tex)
        ls3d_sync_material_flags(material)

    def parent_to_bone(self, obj, bone_name, frame_id=None):

        # Find the correct armature that owns this bone
        armature = getattr(self, 'bone_to_armature', {}).get(frame_id, self.armature) if frame_id is not None else self.armature
        if not armature:
            return

        if bone_name not in armature.data.bones:
            return

        bone = armature.data.bones[bone_name]

        obj.parent      = armature
        obj.parent_type = 'BONE'
        obj.parent_bone = bone_name

        # Blender's BONE parenting formula is:
        #   world_child = bone.matrix_local @ Translation(0, bone.length, 0) @ MPI @ basis
        #
        # We want: world_child = bone_game_world @ file_local_TRS
        #   where bone_game_world is the WITH-SCALE world (including all ancestor
        #   joint scales) — this is what the game engine uses for child frames.
        #
        # Solve:
        #   bone.matrix_local @ Translation(0, L, 0) @ MPI = bone_game_world
        #   MPI = Translation(0, -L, 0) @ bone.matrix_local.inverted() @ bone_game_world
        #
        # Translation(0, -L, 0)  → cancels the tail offset
        # bone.matrix_local.inverted() @ bone_world_original → corrects for roll/rotation
        #   difference between what build_armature baked into the bone vs. the game matrix

        bone_world_original = self.bone_world_matrices.get(frame_id) if frame_id is not None else None

        if bone_world_original is not None:
            obj.matrix_parent_inverse = (
                Matrix.Translation((0, -bone.length, 0))
                @ bone.matrix_local.inverted()
                @ bone_world_original
            )
        else:
            obj.matrix_parent_inverse = Matrix.Translation((0, -bone.length, 0))

    def build_armature(self):
        if not self.joints:
            return

        world_matrices = {}

        def compute_world(frame_id):
            if frame_id in world_matrices:
                return world_matrices[frame_id]
            local = self.frame_matrices.get(frame_id)
            if local is None:
                return None
            parent = next((p for (c, p) in self.parenting_info if c == frame_id), None)
            if parent:
                parent_world = compute_world(parent)
                world = parent_world @ local if parent_world else local
            else:
                world = local
            world_matrices[frame_id] = world
            return world

        for joint in self.joints:
            compute_world(joint["frame_id"])

        # Pure-rotation world chain — no scale contamination.
        # world.to_3x3().normalized().col[1] is wrong when any ancestor has
        # non-uniform ls3d_joint_scale: normalising columns of R@S gives the
        # wrong orientation.  Chain only quaternions instead.
        exact_rot_cache = {}
        def exact_world_rot(frame_id):
            if frame_id in exact_rot_cache:
                return exact_rot_cache[frame_id]
            transform = self.frame_transforms.get(frame_id)
            if transform is None:
                exact_rot_cache[frame_id] = Quaternion()
                return exact_rot_cache[frame_id]
            _, local_rot, _ = transform
            parent_fid = next((p for (c, p) in self.parenting_info if c == frame_id), None)
            q = local_rot if parent_fid is None else exact_world_rot(parent_fid) @ local_rot
            exact_rot_cache[frame_id] = q
            return q

        # ── Scale-free world chain ───────────────────────────────────────────
        # Bone heads are placed at positions computed WITHOUT joint scale,
        # so the armature shows the "design" skeleton.  Joint scale is stored
        # in ls3d_joint_scale and only affects the custom shape display.
        joint_frame_ids = {j["frame_id"] for j in self.joints}

        noscale_matrices = {}
        def compute_world_noscale(frame_id):
            if frame_id in noscale_matrices:
                return noscale_matrices[frame_id]
            local = self.frame_matrices.get(frame_id)
            if local is None:
                return None
            # Strip scale ONLY from joint frames; non-joint frames (like
            # the skin mesh "base") keep their scale since it is part of
            # the scene transform, not a joint property.
            if frame_id in joint_frame_ids:
                loc_ns, rot_ns, _ = local.decompose()
                local_ns = Matrix.LocRotScale(loc_ns, rot_ns, Vector((1, 1, 1)))
            else:
                local_ns = local.copy()
            parent = next((p for (c, p) in self.parenting_info if c == frame_id), None)
            if parent:
                parent_ns = compute_world_noscale(parent)
                world = parent_ns @ local_ns if parent_ns else local_ns
            else:
                world = local_ns
            noscale_matrices[frame_id] = world
            return world

        for joint in self.joints:
            compute_world_noscale(joint["frame_id"])

        # ── Group joints into separate armatures ─────────────────────────────
        # Each joint traces its parent chain upward. The first non-joint frame
        # it reaches is the "root parent" (typically a SINGLEMESH). All joints
        # sharing the same root parent belong to the same armature.
        parent_lookup   = {c: p for c, p in self.parenting_info}

        def find_root_parent(frame_id):
            """Walk up from a joint until we reach a non-joint frame."""
            fid = parent_lookup.get(frame_id)
            while fid is not None and fid in joint_frame_ids:
                fid = parent_lookup.get(fid)
            return fid  # None or the non-joint parent frame ID

        # Build groups: root_parent_fid → [joint, ...]
        armature_groups = {}
        for joint in self.joints:
            root_fid = find_root_parent(joint["frame_id"])
            armature_groups.setdefault(root_fid, []).append(joint)

        # skinned_meshes now stores frame_id directly (not name),
        # so we can match to armature_groups without name lookups.

        # ── Create one armature per group ────────────────────────────────────
        self.armatures = {}           # root_fid → armature_obj
        self.mesh_to_armature = {}    # mesh_obj.name → armature_obj
        self.bone_to_armature = {}    # frame_id → armature_obj

        sphere = bpy.data.objects.get("LS3D_JointShape")
        if not sphere:
            sphere = bpy.data.objects.new("LS3D_JointShape", None)
            sphere.empty_display_type = 'SPHERE'
            sphere.empty_display_size = 1.0
            bpy.context.collection.objects.link(sphere)

        for root_fid, group_joints in armature_groups.items():
            # Determine armature name from associated skin mesh
            arm_name = None
            for _, _, skin_fid, _ in self.skinned_meshes:
                if skin_fid == root_fid:
                    skin_obj = self.frames_map.get(skin_fid)
                    if skin_obj is not None and hasattr(skin_obj, 'name'):
                        arm_name = skin_obj.name + "_Armature"
                    break
            if not arm_name:
                arm_name = (group_joints[0]["name"] + "_Armature")

            arm_data = bpy.data.armatures.new(arm_name)
            arm_obj  = bpy.data.objects.new(arm_name, arm_data)
            bpy.context.collection.objects.link(arm_obj)
            self.armatures[root_fid] = arm_obj

            bpy.context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='EDIT')

            bone_lookup  = {}
            FIXED_LENGTH = 0.1

            for joint in group_joints:
                frame_id = joint["frame_id"]
                name     = joint["name"]
                world    = world_matrices.get(frame_id)
                noscale  = noscale_matrices.get(frame_id)
                if world is None or noscale is None:
                    continue

                eb = arm_data.edit_bones.new(name)
                eb.use_connect = False

                # Place bone heads at NOSCALE world positions — joint scale
                # is NOT baked into the skeleton.
                mat3    = exact_world_rot(frame_id).to_matrix()
                eb.head = noscale.to_translation()
                eb.tail = eb.head + mat3.col[1] * FIXED_LENGTH
                eb.align_roll(mat3.col[2])

                blender_name                           = eb.name
                # bone_world_matrices stores the WITH-SCALE world so that
                # MPI places parented objects (gun1, gun2, etc.) at their
                # correct game positions.  The game chains T@R@S including
                # joint scale, so child frames must be relative to the
                # scaled bone world — not the noscale skeleton display.
                self.bone_world_matrices[frame_id]     = world.copy()
                self.bones_map[frame_id]               = blender_name
                bone_lookup[frame_id]                  = eb
                self.bone_to_armature[frame_id]        = arm_obj

            for joint in group_joints:
                frame_id        = joint["frame_id"]
                parent_frame_id = joint["parent_frame_id"]
                if parent_frame_id in bone_lookup:
                    bone_lookup[frame_id].parent = bone_lookup[parent_frame_id]

            # ── Create blend bone (mesh frame bone) ────���───────────────────
            # The SINGLEMESH frame (root_fid) is the actual parent of all
            # root bones in the 4DS hierarchy.  In the skin data,
            # parent_joint_id == 0 means "blend the (1-weight) portion with
            # this frame's transform."  We represent it as a bone so the
            # armature modifier can apply the correct blend ratio.
            mesh_noscale = noscale_matrices.get(root_fid)
            mf_pos = mesh_noscale if mesh_noscale is not None else world_matrices.get(root_fid)
            if mf_pos is not None:
                skin_obj    = self.frames_map.get(root_fid)
                mf_name     = skin_obj.name if skin_obj else "base"
                mf_rot      = exact_world_rot(root_fid).to_matrix()
                mf_eb       = arm_data.edit_bones.new(mf_name)
                mf_eb.use_connect = False
                mf_eb.head  = mf_pos.to_translation()
                mf_eb.tail  = mf_eb.head + mf_rot.col[1] * FIXED_LENGTH
                mf_eb.align_roll(mf_rot.col[2])
                mf_blender_name = mf_eb.name

            bpy.ops.object.mode_set(mode='OBJECT')

            # Mark the mesh-frame bone as the blend bone and register it
            # in bone_nodes so that skinning weights with parent_joint_id == 0
            # (or current_joint_id == 0 for root nonweighted verts) get
            # assigned to this bone.
            if mf_pos is not None and mf_blender_name in arm_obj.pose.bones:
                arm_obj.pose.bones[mf_blender_name]["ls3d_is_blend_bone"] = True
                self.bone_nodes[0] = mf_blender_name

            for joint in group_joints:
                blender_name = self.bones_map.get(joint["frame_id"])
                if blender_name and blender_name in arm_obj.pose.bones:
                    pbone            = arm_obj.pose.bones[blender_name]
                    pbone.cull_flags = joint["cull_flags"]
                    pbone.user_props = joint["user_props"]
                    transform = self.frame_transforms.get(joint["frame_id"])
                    if transform:
                        _, _, scl = transform
                        pbone["ls3d_joint_scale"] = (scl.x, scl.y, scl.z)

                    pbone.lock_scale[0] = True
                    pbone.lock_scale[1] = True
                    pbone.lock_scale[2] = True

                    for axis_idx, axis_name in enumerate(('x', 'y', 'z')):
                        fcurve = arm_obj.driver_add(
                            f'pose.bones["{blender_name}"].custom_shape_scale_xyz',
                            axis_idx
                        )
                        drv = fcurve.driver
                        drv.type = 'SCRIPTED'
                        drv.expression = f'joint_scale[{axis_idx}] * 0.03'

                        var = drv.variables.new()
                        var.name = 'joint_scale'
                        var.type = 'SINGLE_PROP'
                        tgt = var.targets[0]
                        tgt.id_type       = 'OBJECT'
                        tgt.id            = arm_obj
                        tgt.data_path     = f'pose.bones["{blender_name}"]["ls3d_joint_scale"]'

            for bone in arm_obj.pose.bones:
                if bone.get("ls3d_is_blend_bone"):
                    # Blend bone: octahedral display, no custom shape
                    bone.custom_shape = None
                    bone.bone.show_wire = True
                    continue
                bone.custom_shape               = sphere
                bone.use_custom_shape_bone_size = False
                scl = bone.get("ls3d_joint_scale", (1.0, 1.0, 1.0))

        # Build mesh_to_armature mapping for apply_skinning
        # skinned_meshes stores (lod_obj, weights, frame_id, is_primary)
        for mesh_obj, _, skin_fid, _ in self.skinned_meshes:
            if skin_fid in self.armatures:
                self.mesh_to_armature[mesh_obj.name] = self.armatures[skin_fid]

        # Set self.armature to the first one for backward compatibility
        if self.armatures:
            self.armature = next(iter(self.armatures.values()))

        if sphere.name in bpy.context.collection.objects:
            bpy.context.collection.objects.unlink(sphere)

    def apply_skinning(self, obj, weights, reparent=True):

        # Find the correct armature for this mesh
        armature = getattr(self, 'mesh_to_armature', {}).get(obj.name, self.armature)
        if not armature:
            return

        accumulated = {}

        for vertex_index, current_joint_id, weight, parent_joint_id in weights:

            bone_name = self.bone_nodes.get(current_joint_id)
            if not bone_name:
                continue

            key = (vertex_index, bone_name)
            accumulated[key] = accumulated.get(key, 0.0) + weight

            if weight < 1.0 and parent_joint_id >= 0:
                parent_bone_name = self.bone_nodes.get(parent_joint_id)
                if parent_bone_name and parent_bone_name != bone_name:
                    pkey = (vertex_index, parent_bone_name)
                    accumulated[pkey] = accumulated.get(pkey, 0.0) + (1.0 - weight)

        for (vertex_index, bone_name), total_weight in accumulated.items():
            if bone_name not in obj.vertex_groups:
                obj.vertex_groups.new(name=bone_name)
            obj.vertex_groups[bone_name].add([vertex_index], total_weight, 'REPLACE')

        # LOD 0 gets reparented to the armature (primary mesh).
        # LOD 1+ stay as children of mesh_obj — only add the modifier.
        if reparent:
            obj.parent = armature
        mod = obj.modifiers.new("Armature", 'ARMATURE')
        mod.object = armature

    def deserialize_joint(self, f, name, frame_id, parent_frame_id, cull_flags=0, user_props=""):

        # Read the 16 floats (64 bytes) representing the matrix in the payload
        inverse_vals = struct.unpack("<16f", f.read(64))
        
        # Reconstruct Blender Matrix
        # Note: We read it row-by-row as stored in the file
        inverse_matrix = Matrix((
            inverse_vals[0:4],
            inverse_vals[4:8],
            inverse_vals[8:12],
            inverse_vals[12:16],
        ))

        joint_id = struct.unpack("<I", f.read(4))[0] + 1

        self.joints.append({
            "name":            name,
            "frame_id":        frame_id,
            "parent_frame_id": parent_frame_id,
            "joint_id":        joint_id,
            "inverse_bind":    inverse_matrix,
            "cull_flags":      cull_flags,
            "user_props":      user_props,
        })

        self.bone_nodes[joint_id] = name
        self.bones_map[frame_id]  = name
        
    def deserialize_singlemesh(self, f, lod_objects, frame_id):
        for lod_index, lod_obj in enumerate(lod_objects):

            num_bones        = struct.unpack("<B", f.read(1))[0]
            root_nonweighted = struct.unpack("<I", f.read(4))[0]

            f.read(12)  # root AABB min
            f.read(12)  # root AABB max

            reconstructed_weights = []
            vertex_cursor = 0

            for group_idx in range(num_bones):

                f.read(64)  # inverse transform matrix

                bone_nonweighted = struct.unpack("<I", f.read(4))[0]
                bone_weighted    = struct.unpack("<I", f.read(4))[0]
                parent_joint_id  = struct.unpack("<I", f.read(4))[0]

                f.read(12)  # bone AABB min
                f.read(12)  # bone AABB max

                current_joint_id = group_idx + 1

                for _ in range(bone_nonweighted):
                    reconstructed_weights.append(
                        (vertex_cursor, current_joint_id, 1.0, 0)
                    )
                    vertex_cursor += 1

                for _ in range(bone_weighted):
                    weight_val = struct.unpack("<f", f.read(4))[0]
                    reconstructed_weights.append(
                        (vertex_cursor, current_joint_id, weight_val, parent_joint_id)
                    )
                    vertex_cursor += 1

            for _ in range(root_nonweighted):
                reconstructed_weights.append(
                    (vertex_cursor, 0, 1.0, 0)
                )
                vertex_cursor += 1

            # Only LOD 0 gets reparented to the armature; LOD 1+ stay as
            # children of mesh_obj so their position is preserved.
            # Store frame_id (not name) so build_armature can match reliably
            # even when Blender renames objects to avoid conflicts.
            self.skinned_meshes.append((lod_obj, reconstructed_weights, frame_id, lod_index == 0))

    def deserialize_dummy(self, f, empty, pos, rot, scale):
        # Reads bbox but does NOT apply transforms (handled by apply_deferred_parenting)
        min_raw = struct.unpack("<3f", f.read(12))
        max_raw = struct.unpack("<3f", f.read(12))
        
        b_min = [min_raw[0], min_raw[2], min_raw[1]]
        b_max = [max_raw[0], max_raw[2], max_raw[1]]
        
        empty["bbox_min"] = b_min
        empty["bbox_max"] = b_max
        
        width = abs(b_max[0] - b_min[0])
        depth = abs(b_max[1] - b_min[1])
        height = abs(b_max[2] - b_min[2])
        
        max_dim = max(width, depth, height)

        empty.empty_display_type = "CUBE"
        empty.empty_display_size = max_dim * 0.5
        empty.show_name = True

    def deserialize_target(self, f, obj, pos, rot, scl):
        flags     = struct.unpack("<H", f.read(2))[0]
        num_links = struct.unpack("<B", f.read(1))[0]
        link_ids  = list(struct.unpack(f"<{num_links}H", f.read(2 * num_links)))

        obj.ls3d_target_flags = flags
        # Stash raw 1-based frame IDs for post-processing resolution
        obj["_target_link_ids"] = link_ids

        obj.empty_display_type = "PLAIN_AXES"
        #obj.empty_display_size = 0.1
        obj.show_name = True
        # Transform applied by apply_deferred_parenting, same as FRAME_DUMMY
    
    def deserialize_morph(self, f, lod_objects):
        num_targets = struct.unpack("<B", f.read(1))[0]
        if num_targets == 0:
            return

        num_regions = struct.unpack("<B", f.read(1))[0]
        num_lods    = struct.unpack("<B", f.read(1))[0]

        for lod_id in range(num_lods):
            target_obj = lod_objects[lod_id] if lod_id < len(lod_objects) else lod_objects[0]

            for region_id in range(num_regions):
                num_verts = struct.unpack("<H", f.read(2))[0]
                if num_verts == 0:
                    continue

                region_targets = [[] for _ in range(num_targets)]
                for _ in range(num_verts):
                    for t in range(num_targets):
                        px, py, pz = struct.unpack("<3f", f.read(12))
                        f.read(12)  # normal — recomputed from mesh on export
                        region_targets[t].append(Vector((px, pz, py)))  # Y↔Z

                f.read(1)  # flag byte
                indices = [struct.unpack("<H", f.read(2))[0] for _ in range(num_verts)]

                for t in range(num_targets):
                    name = f"G{region_id+1}_Basis" if t == 0 else f"G{region_id+1}_Target{t}"
                    key = target_obj.shape_key_add(name=name, from_mix=False)
                    key.value = 0.0
                    for i, vi in enumerate(indices):
                        if vi < len(key.data):
                            key.data[vi].co = region_targets[t][i]

        # Populate ls3d_morph_groups on the primary LOD object
        primary = lod_objects[0]
        primary.ls3d_morph_groups.clear()
        for region_id in range(num_regions):
            g = primary.ls3d_morph_groups.add()
            g.name = f"Group{region_id + 1}"
            for t in range(num_targets):
                name = f"G{region_id+1}_Basis" if t == 0 else f"G{region_id+1}_Target{t}"
                entry = g.targets.add()
                entry.shape_key_name = name

        f.read(12 + 12 + 12 + 4)  # bounding box — recomputed on export

    def apply_deferred_parenting(self):

        bone_parented = set()

        # --------------------------------------------------
        # 1. Establish hierarchy
        # --------------------------------------------------

        for frame_index, parent_id in self.parenting_info:

            if frame_index not in self.frames_map or parent_id not in self.frames_map:
                continue
            if frame_index == parent_id:
                continue

            child_obj    = self.frames_map[frame_index]
            parent_entry = self.frames_map[parent_id]
            parent_type  = self.frame_types.get(parent_id, 0)

            if child_obj is None or isinstance(child_obj, str):
                continue

            # -------------------------------
            # Joint parenting
            # -------------------------------

            if parent_type == FRAME_JOINT:

                if self.armature:
                    # bones_map now stores the Blender bone name (set in build_armature).
                    p_name = self.bones_map.get(parent_id)
                    # Find correct armature for this bone (keyed by frame_id)
                    bone_arm = getattr(self, 'bone_to_armature', {}).get(parent_id, self.armature)

                    if p_name and bone_arm and p_name in bone_arm.data.bones:

                        self.parent_to_bone(child_obj, p_name, frame_id=parent_id)

                        # Apply file-local TRS immediately while parent is established.
                        # With the correct MPI, these values produce:
                        #   world_child = bone_world @ file_local_TRS
                        pos, rot, scl = self.frame_transforms[frame_index]

                        child_obj.rotation_mode       = 'QUATERNION'
                        child_obj.location            = pos
                        child_obj.rotation_quaternion = rot
                        child_obj.scale               = scl

                        bone_parented.add(frame_index)

            # -------------------------------
            # Object parenting
            # -------------------------------

            elif not isinstance(parent_entry, str):

                child_obj.parent                    = parent_entry
                child_obj.matrix_parent_inverse     = Matrix.Identity(4)

        # --------------------------------------------------
        # 2. Apply transforms to everything else
        # --------------------------------------------------

        for fid, transform_data in self.frame_transforms.items():

            if fid in bone_parented:
                continue  # already applied above

            if fid in self.frames_map:

                obj = self.frames_map[fid]

                if not isinstance(obj, str) and obj is not None:

                    pos, rot, scl = transform_data

                    obj.rotation_mode       = 'QUATERNION'
                    obj.location            = pos
                    obj.rotation_quaternion = rot
                    obj.scale               = scl

    def resolve_target_links(self, frames):
        for frame_obj in frames:
            link_ids = frame_obj.get("_target_link_ids")
            if link_ids is None:
                continue
            for fid in link_ids:
                linked_obj = self.frames_map.get(fid)
                bone_name  = self.bones_map.get(fid)

                if linked_obj is not None:
                    entry               = frame_obj.ls3d_target_objects.add()
                    entry.name          = linked_obj.name
                    entry.target_object = linked_obj
                    entry.target_path   = linked_obj.name  # legacy compat
                elif bone_name is not None:
                    # Find which armature owns this bone (keyed by frame_id)
                    bone_arm = getattr(self, 'bone_to_armature', {}).get(fid, self.armature)
                    if bone_arm is not None:
                        entry                 = frame_obj.ls3d_target_objects.add()
                        entry.name            = bone_name
                        entry.target_armature = bone_arm
                        entry.bone_name       = bone_name
                        entry.target_path     = f"BONE:{bone_arm.name}:{bone_name}"  # legacy compat
                else:
                    print(f"WARNING: Target '{frame_obj.name}' link ID {fid} not found")

            del frame_obj["_target_link_ids"]
            sync_track_to_constraints(frame_obj)

    def deserialize_frame(self, f, materials, frames):

        # =================================================
        # 1. READ HEADER & TRANSFORM
        # =================================================

        raw = f.read(1)
        if not raw:
            return False

        frame_type = struct.unpack("<B", raw)[0]

        visual_type = 0
        visual_flags = (0, 0)

        if frame_type == FRAME_VISUAL:
            visual_type = struct.unpack("<B", f.read(1))[0]
            visual_flags = struct.unpack("<2B", f.read(2))

        parent_id = struct.unpack("<H", f.read(2))[0]

        # Store frame id immediately
        current_frame_id = self.frame_index

        # -------------------------
        # Transform
        # -------------------------

        pos_raw = struct.unpack("<3f", f.read(12))
        scl_raw = struct.unpack("<3f", f.read(12))
        rot_raw = struct.unpack("<4f", f.read(16))

        pos = Vector((pos_raw[0], pos_raw[2], pos_raw[1]))
        scl = Vector((scl_raw[0], scl_raw[2], scl_raw[1]))
        rot = Quaternion((rot_raw[0], rot_raw[1], rot_raw[3], rot_raw[2]))

        self.frame_transforms[current_frame_id] = (pos, rot, scl)
        self.frame_matrices[current_frame_id] = Matrix.LocRotScale(pos, rot, scl)

        # -------------------------
        # Common data
        # -------------------------

        cull_flags = struct.unpack("<B", f.read(1))[0]
        name = self.read_string(f)
        user_props = self.read_string(f)

        self.frame_types[current_frame_id] = frame_type

        if parent_id > 0:
            self.parenting_info.append((current_frame_id, parent_id))

        # =================================================
        # 2. JOINT HANDLING (NO OBJECT CREATED)
        # =================================================

        if frame_type == FRAME_JOINT:

            self.deserialize_joint(f, name, current_frame_id, parent_id, cull_flags, user_props,)

            self.frames_map[current_frame_id] = None
            self.frame_index += 1
            return True

        # =================================================
        # 3. OBJECT CREATION
        # =================================================

        obj = None

        if frame_type == FRAME_VISUAL:

            if visual_type == VISUAL_LENSFLARE:
                obj = self.deserialize_lensflare(f, name, pos, rot, scl)

            else:
                mesh_data = bpy.data.meshes.new(name)
                obj = bpy.data.objects.new(name, mesh_data)
                bpy.context.collection.objects.link(obj)

        elif frame_type in (FRAME_SECTOR, FRAME_OCCLUDER):
            mesh_data = bpy.data.meshes.new(name)
            obj = bpy.data.objects.new(name, mesh_data)
            bpy.context.collection.objects.link(obj)

        elif frame_type in (FRAME_DUMMY, FRAME_TARGET):
            obj = bpy.data.objects.new(name, None)
            bpy.context.collection.objects.link(obj)

        # =================================================
        # 4. PAYLOAD
        # =================================================

        if obj:

            frames.append(obj)
            self.frames_map[current_frame_id] = obj
            self.frame_index += 1

            inst_id = 0
            v_per_lod = []
            lod_objects = []

            if frame_type == FRAME_VISUAL and visual_type != VISUAL_LENSFLARE:

                # Geometry first
                if visual_type == VISUAL_MIRROR:
                    self.deserialize_mirror(f, obj)

                else:
                    inst_id, v_per_lod, lod_objects = self.deserialize_object(
                        f,
                        materials,
                        obj,
                        obj.data,
                        cull_flags
                    )

                # Skin block — pass the full list of LOD objects so every LOD
                # gets its own weights and armature modifier applied correctly.
                if visual_type == VISUAL_SINGLEMESH:
                    self.deserialize_singlemesh(f, lod_objects, current_frame_id)

                elif visual_type == VISUAL_SINGLEMORPH:
                    self.deserialize_singlemesh(f, lod_objects, current_frame_id)
                    self.deserialize_morph(f, lod_objects)

                # Other visual logic
                elif inst_id == 0:

                    if visual_type == VISUAL_BILLBOARD:
                        self.deserialize_billboard(f, obj)

                    elif visual_type == VISUAL_MORPH:
                        self.deserialize_morph(f, lod_objects)

            elif frame_type == FRAME_SECTOR:
                self.deserialize_sector(f, obj)

            elif frame_type == FRAME_DUMMY:
                self.deserialize_dummy(f, obj, pos, rot, scl)

            elif frame_type == FRAME_TARGET:
                self.deserialize_target(f, obj, pos, rot, scl)

            elif frame_type == FRAME_OCCLUDER:
                self.deserialize_occluder(f, obj, pos, rot, scl)

            # -------------------------
            # Properties
            # -------------------------

            obj.ls3d_frame_type = str(frame_type)
            obj.ls3d_frame_type_override = frame_type
            obj.cull_flags = cull_flags
            obj.ls3d_user_props = user_props

            if frame_type == FRAME_VISUAL:
                obj.visual_type = str(visual_type)
                obj.render_flags = visual_flags[0]
                obj.render_flags2 = visual_flags[1]

        else:
            # If no object was created but also not a joint
            self.frames_map[current_frame_id] = None
            self.frame_index += 1

        return True

    def deserialize_material(self, f, mat_index):

        mat = bpy.data.materials.new(f"4ds_material_{mat_index}")

        # -------------------------------------------------
        # 1. FLAGS (U32 from file)
        # -------------------------------------------------
        flags_unsigned = struct.unpack("<I", f.read(4))[0]

        # Convert to signed 32-bit for Blender storage
        flags_signed = (
            flags_unsigned
            if flags_unsigned < 0x80000000
            else flags_unsigned - 0x100000000
        )

        mat.ls3d_material_flags = flags_signed

        flags = flags_unsigned  # use unsigned for bit testing

        # -------------------------------------------------
        # 2. COLORS
        # -------------------------------------------------
        mat.ls3d_ambient_color  = struct.unpack("<3f", f.read(12))
        mat.ls3d_diffuse_color  = struct.unpack("<3f", f.read(12))
        mat.ls3d_emission_color = struct.unpack("<3f", f.read(12))
        opacity = struct.unpack("<f", f.read(4))[0]

        # -------------------------------------------------
        # 3. FLAGS
        # -------------------------------------------------
        env_enabled   = (flags & MTL_ENV_ENABLE) != 0
        alpha_enabled = (flags & MTL_ALPHA_ENABLE) != 0
        alpha_tex     = (flags & MTL_ALPHATEX) != 0
        image_alpha   = (flags & MTL_ALPHA_IN_TEX) != 0
        color_key     = (flags & MTL_ALPHA_COLORKEY) != 0
        additive      = (flags & MTL_ALPHA_ADDITIVE) != 0
        animated_diff = (flags & MTL_DIFFUSE_ANIMATED) != 0

        env_tex_name = ""
        diffuse_tex_name = ""
        alpha_tex_name = ""
        env_amount = 0.0

        # -------------------------------------------------
        # 4. ENVIRONMENT
        # -------------------------------------------------
        if env_enabled:
            env_amount = struct.unpack("<f", f.read(4))[0]

            length = struct.unpack("<B", f.read(1))[0]
            if length > 0:
                env_tex_name = f.read(length).decode("windows-1250", errors="replace")

        # -------------------------------------------------
        # 5. DIFFUSE (ALWAYS PRESENT)
        # -------------------------------------------------
        length = struct.unpack("<B", f.read(1))[0]
        if length > 0:
            diffuse_tex_name = f.read(length).decode("windows-1250", errors="replace")

        # -------------------------------------------------
        # 6. ALPHA MAP
        # -------------------------------------------------
        if (
            len(diffuse_tex_name) > 0 and
            #alpha_enabled and
            alpha_tex and
            not image_alpha and
            not color_key and
            not additive
        ):
            length_alpha = struct.unpack("<B", f.read(1))[0]
            if length_alpha > 0:
                alpha_tex_name = f.read(length_alpha).decode("windows-1250", errors="replace")

        # -------------------------------------------------
        # 7. ANIMATION
        # -------------------------------------------------
        if animated_diff:
            mat.ls3d_anim_frames = struct.unpack("<I", f.read(4))[0]
            f.read(2) # unknown 1
            mat.ls3d_anim_period = struct.unpack("<I", f.read(4))[0]
            f.read(4) # unknown 2
            f.read(4) # unknown 3

        # -------------------------------------------------
        # APPLY
        # -------------------------------------------------
        self.set_material_data(
            mat,
            diffuse_tex_name.lower(),
            alpha_tex_name.lower(),
            env_tex_name.lower(),
            mat.ls3d_emission_color,
            opacity,
            env_amount,
            color_key
        )

        return mat

    # def deserialize_material(self, f):
    #     mat = bpy.data.materials.new("material")
    #     flags = struct.unpack("<I", f.read(4))[0]

    #     use_diffuse_tex = (flags & MTL_DIFFUSE_ENABLE) != 0
    #     use_color_key = (flags & MTL_ALPHA_COLORKEY) != 0
    #     ambient = struct.unpack("<3f", f.read(12))
    #     diffuse = struct.unpack("<3f", f.read(12))
    #     emission = struct.unpack("<3f", f.read(12))
    #     alpha = struct.unpack("<f", f.read(4))[0]

    #     metallic = 0.0
    #     diffuse_tex = ""
    #     env_tex = ""
    #     has_tex = False
    #     if flags & MTL_ENV_ENABLE:  # Env texture
    #         metallic = struct.unpack("<f", f.read(4))[0]
    #         env_tex = self.read_string(f).lower()

    #     if use_diffuse_tex:
    #         has_tex = True
    #         diffuse_tex = self.read_string(f).lower()
    #         if len(diffuse_tex) > 0:
    #             mat.name = diffuse_tex

    #     alpha_tex = ""
    #     if (flags & MTL_ALPHA_ENABLE) and (flags & MTL_ALPHATEX):
    #         has_tex = True
    #         alpha_tex = self.read_string(f).lower()

    #     if not has_tex:
    #         f.read(1)

    #     if flags & MTL_ALPHA_ANIMATED:  # Animated alpha
    #         struct.unpack("<I", f.read(4))  # Frames
    #         f.read(2)  # Skip
    #         struct.unpack("<I", f.read(4))  # Frame length
    #         f.read(8)  # Skip

    #     if flags & MTL_DIFFUSE_ANIMATED:  # Animated diffuse
    #         struct.unpack("<I", f.read(4))  # Frames
    #         f.read(2)  # Skip
    #         struct.unpack("<I", f.read(4))  # Frame length
    #         f.read(8)  # Skip

    #     self.set_material_data(
    #         mat, diffuse_tex, alpha_tex, env_tex, emission, alpha, metallic, use_color_key
    #     )
    #     return mat

    def deserialize_object(self, f, materials, mesh_obj, mesh_data, culling_flags):
        
        raw_id = f.read(2)
        if not raw_id:
            return -1, [], []

        instance_id = struct.unpack("<H", raw_id)[0]
        if instance_id > 0:
            return instance_id, [], []

        num_lods = struct.unpack("<B", f.read(1))[0]
        v_counts = []
        lod_objects = []   # track the Blender object for each LOD

        for lod_idx in range(num_lods):

            dist = struct.unpack("<f", f.read(4))[0]

            if lod_idx == 0:
                curr_mesh = mesh_data
                target_obj = mesh_obj
            else:
                curr_mesh = bpy.data.meshes.new(f"{mesh_obj.name}_lod{lod_idx}")
                target_obj = bpy.data.objects.new(curr_mesh.name, curr_mesh)
                target_obj.parent = mesh_obj
                target_obj.matrix_parent_inverse = Matrix.Identity(4)
                bpy.context.collection.objects.link(target_obj)
                target_obj.hide_set(True)
                target_obj.hide_render = True

            lod_objects.append(target_obj)   # track this LOD's object
            target_obj.ls3d_lod_dist = dist

            # -------------------------------------
            # 1. READ VERTEX DATA
            # -------------------------------------
            num_v = struct.unpack("<H", f.read(2))[0]
            v_counts.append(num_v)

            pos_buf = [None] * num_v
            norm_buf = [None] * num_v
            uv_buf = [None] * num_v

            for i in range(num_v):
                d = struct.unpack("<3f3f2f", f.read(32))
                
                # --- Position (Swapped Y/Z) ---
                px, py, pz = d[0], d[2], d[1]
                
                # CRITICAL FIX: Blender crashes if Positions are NaN/Inf.
                # We MUST sanitize this even if we want "raw" values.
                if not (math.isfinite(px) and math.isfinite(py) and math.isfinite(pz)):
                    px, py, pz = 0.0, 0.0, 0.0
                pos_buf[i] = (px, py, pz)

                # --- Normal (Swapped Y/Z) ---
                nx, ny, nz = d[3], d[5], d[4]
                
                # CRITICAL FIX: Sanitize Normals immediately
                if not (math.isfinite(nx) and math.isfinite(ny) and math.isfinite(nz)):
                    nx, ny, nz = 0.0, 1.0, 0.0
                # Fix Zero-Length normals (Divide by Zero crash)
                elif abs(nx) < 1e-6 and abs(ny) < 1e-6 and abs(nz) < 1e-6:
                    nx, ny, nz = 0.0, 1.0, 0.0
                norm_buf[i] = (nx, ny, nz)

                # --- UV ---
                tu, tv = d[6], 1.0 - d[7]
                # Sanitize UVs just in case
                if not (math.isfinite(tu) and math.isfinite(tv)):
                    tu, tv = 0.0, 0.0
                uv_buf[i] = (tu, tv)

            # -------------------------------------
            # 2. READ FACE DATA
            # -------------------------------------
            faces_list = []
            face_mat_indices = []

            num_grps = struct.unpack("<B", f.read(1))[0]

            for _ in range(num_grps):
                num_f = struct.unpack("<H", f.read(2))[0]
                raw_indices = f.read(num_f * 6)
                indices = struct.unpack(f"<{num_f * 3}H", raw_indices)
                
                m_id = struct.unpack("<H", f.read(2))[0]
                
                slot = 0
                # UPDATE: Direct 1-based access (Matches your new import_file logic)
                if m_id < len(self.materials) and self.materials[m_id]:
                    m = self.materials[m_id]
                    if m.name not in curr_mesh.materials:
                        curr_mesh.materials.append(m)
                    slot = curr_mesh.materials.find(m.name)

                for k in range(0, len(indices), 3):
                    idx0 = indices[k]
                    idx1 = indices[k+2]
                    idx2 = indices[k+1]
                    
                    if idx0 >= num_v or idx1 >= num_v or idx2 >= num_v:
                        continue
                    
                    # CRITICAL FIX: Filter Degenerate Faces (Crash protection)
                    if idx0 == idx1 or idx1 == idx2 or idx2 == idx0:
                        continue

                    faces_list.append((idx0, idx1, idx2))
                    face_mat_indices.append(slot)

            # -------------------------------------
            # 3. BUILD MESH
            # -------------------------------------
            curr_mesh.from_pydata(pos_buf, [], faces_list)
            
            # Update mesh structure (Required before accessing loops)
            curr_mesh.update()

            # Assign Materials
            if face_mat_indices and len(curr_mesh.polygons) == len(face_mat_indices):
                curr_mesh.polygons.foreach_set("material_index", face_mat_indices)

            curr_mesh.polygons.foreach_set(
                "use_smooth", [True] * len(curr_mesh.polygons)
            )

            # -------------------------------------
            # 4. ASSIGN NORMALS & UVs
            # -------------------------------------
            if len(curr_mesh.loops) > 0:
                
                uv_data = None
                if uv_buf:
                    uv_layer = curr_mesh.uv_layers.new(name="UVMap")
                    uv_data = uv_layer.data
                
                loop_normals = [None] * len(curr_mesh.loops)
                
                for i, loop in enumerate(curr_mesh.loops):
                    vi = loop.vertex_index
                    
                    # Assign UV
                    if uv_data:
                        uv_data[i].uv = uv_buf[vi]
                    
                    # Assign Normal (Pre-sanitized in step 1)
                    loop_normals[i] = norm_buf[vi]

                # Apply Normals
                try:
                    curr_mesh.normals_split_custom_set(loop_normals)
                except RuntimeError as e:
                    print(f"LS3D Warning: Normal set failed for {mesh_obj.name}: {e}")

            # Final update
            curr_mesh.update()

        return 0, v_counts, lod_objects
    
    def deserialize_sector(self, f, mesh_obj):
        # -------------------------------------------------
        # Force Sector Frame Type (authoritative import)
        # -------------------------------------------------
        mesh_obj.ls3d_frame_type_override = 5 # FRAME_SECTOR
        mesh_obj.ls3d_frame_type = '5'

        # -------------------------------------------------
        # Sector Flags
        # -------------------------------------------------
        mesh_obj.ls3d_sector_flags1 = struct.unpack("<i", f.read(4))[0]
        mesh_obj.ls3d_sector_flags2 = struct.unpack("<i", f.read(4))[0]

        # -------------------------------------------------
        # Geometry
        # -------------------------------------------------
        bm = bmesh.new()

        num_verts = struct.unpack("<I", f.read(4))[0]
        num_faces = struct.unpack("<I", f.read(4))[0]

        verts = []
        for _ in range(num_verts):
            x, y, z = struct.unpack("<3f", f.read(12))
            # Convert Mafia (X, Z, Y) -> Blender (X, Y, Z)
            verts.append(bm.verts.new((x, z, y)))

        bm.verts.ensure_lookup_table()

        for _ in range(num_faces):
            i0, i1, i2 = struct.unpack("<3H", f.read(6))
            try:
                # 4DS Winding (0,2,1) -> Blender (0,1,2)
                bm.faces.new((verts[i0], verts[i2], verts[i1]))
            except ValueError:
                pass # Duplicate faces or bad indices

        bm.to_mesh(mesh_obj.data)
        bm.free()

        # -------------------------------------------------
        # Bounding Box
        # -------------------------------------------------
        min_b = struct.unpack("<3f", f.read(12))
        max_b = struct.unpack("<3f", f.read(12))

        mesh_obj.bbox_min = (min_b[0], min_b[2], min_b[1])
        mesh_obj.bbox_max = (max_b[0], max_b[2], max_b[1])

        # -------------------------------------------------
        # Portals
        # -------------------------------------------------
        num_portals = struct.unpack("<B", f.read(1))[0]

        for i in range(num_portals):

            num_pverts = struct.unpack("<B", f.read(1))[0]

            flags = struct.unpack("<I", f.read(4))[0]
            near_r = struct.unpack("<f", f.read(4))[0]
            far_r  = struct.unpack("<f", f.read(4))[0]

            # --- Plane data (Read & Store) ---
            raw_normal = struct.unpack("<3f", f.read(12))
            raw_dot    = struct.unpack("<f", f.read(4))[0]

            # Convert Normal to Blender Space for storage/debug
            # Mafia(X, Z, Y) -> Blender(X, Y, Z)
            blender_plane_normal = [raw_normal[0], raw_normal[2], raw_normal[1]]

            # --- Portal Vertices ---
            p_verts = []
            for _ in range(num_pverts):
                x, y, z = struct.unpack("<3f", f.read(12))
                p_verts.append((x, z, y))

            # --- Create Portal Object ---
            pname = f"{mesh_obj.name}_portal{i+1}"
            p_mesh = bpy.data.meshes.new(pname)
            p_obj = bpy.data.objects.new(pname, p_mesh)

            bpy.context.collection.objects.link(p_obj)
            p_obj.parent = mesh_obj

            # Frame type must match sector
            p_obj.ls3d_frame_type_override = 5 # FRAME_SECTOR
            p_obj.ls3d_frame_type = '5'

            # Store portal data (Standard Props)
            p_obj.ls3d_portal_flags = flags
            p_obj.ls3d_portal_near  = near_r
            p_obj.ls3d_portal_far   = far_r
            
            # Store Plane Data (Custom Props for debug/reference)
            p_obj["ls3d_portal_normal"] = blender_plane_normal
            p_obj["ls3d_portal_dot"] = raw_dot

            # Geometry
            if len(p_verts) >= 3:
                pbm = bmesh.new()
                for v in p_verts:
                    pbm.verts.new(v)
                pbm.verts.ensure_lookup_table()
                try:
                    pbm.faces.new(pbm.verts)
                except ValueError:
                    pass
                pbm.to_mesh(p_mesh)
                pbm.free()

    # def deserialize_sector(self, f, mesh_obj):

    #     # -------------------------------------------------
    #     # Force Sector Frame Type (authoritative import)
    #     # -------------------------------------------------
    #     mesh_obj.ls3d_frame_type_override = FRAME_SECTOR
    #     mesh_obj.ls3d_frame_type = str(FRAME_SECTOR)

    #     # -------------------------------------------------
    #     # Sector Flags
    #     # -------------------------------------------------
    #     mesh_obj.ls3d_sector_flags1 = struct.unpack("<i", f.read(4))[0]
    #     mesh_obj.ls3d_sector_flags2 = struct.unpack("<i", f.read(4))[0]

    #     # -------------------------------------------------
    #     # Geometry
    #     # -------------------------------------------------
    #     bm = bmesh.new()

    #     num_verts = struct.unpack("<I", f.read(4))[0]
    #     num_faces = struct.unpack("<I", f.read(4))[0]

    #     verts = []
    #     for _ in range(num_verts):
    #         x, y, z = struct.unpack("<3f", f.read(12))
    #         verts.append(bm.verts.new((x, z, y)))

    #     bm.verts.ensure_lookup_table()

    #     for _ in range(num_faces):
    #         i0, i1, i2 = struct.unpack("<3H", f.read(6))
    #         try:
    #             bm.faces.new((verts[i0], verts[i2], verts[i1]))
    #         except:
    #             pass

    #     bm.to_mesh(mesh_obj.data)
    #     bm.free()

    #     # -------------------------------------------------
    #     # Bounding Box
    #     # -------------------------------------------------
    #     min_b = struct.unpack("<3f", f.read(12))
    #     max_b = struct.unpack("<3f", f.read(12))

    #     mesh_obj.bbox_min = (min_b[0], min_b[2], min_b[1])
    #     mesh_obj.bbox_max = (max_b[0], max_b[2], max_b[1])

    #     # -------------------------------------------------
    #     # Portals
    #     # -------------------------------------------------
    #     num_portals = struct.unpack("<B", f.read(1))[0]

    #     for i in range(num_portals):

    #         num_pverts = struct.unpack("<B", f.read(1))[0]

    #         flags = struct.unpack("<I", f.read(4))[0]
    #         near_r = struct.unpack("<f", f.read(4))[0]
    #         far_r  = struct.unpack("<f", f.read(4))[0]

    #         # --- Plane data (IMPORTANT) ---
    #         normal = struct.unpack("<3f", f.read(12))
    #         dot    = struct.unpack("<f", f.read(4))[0]

    #         normal = (normal[0], normal[2], normal[1])

    #         # --- Portal Vertices ---
    #         p_verts = []
    #         for _ in range(num_pverts):
    #             x, y, z = struct.unpack("<3f", f.read(12))
    #             p_verts.append((x, z, y))

    #         # --- Create Portal Object ---
    #         pname = f"{mesh_obj.name}_portal{i+1}"
    #         p_mesh = bpy.data.meshes.new(pname)
    #         p_obj = bpy.data.objects.new(pname, p_mesh)

    #         bpy.context.collection.objects.link(p_obj)
    #         p_obj.parent = mesh_obj

    #         # Frame type must match sector
    #         p_obj.ls3d_frame_type_override = FRAME_SECTOR
    #         p_obj.ls3d_frame_type = str(FRAME_SECTOR)

    #         # Store portal data
    #         p_obj.ls3d_portal_flags = flags
    #         p_obj.ls3d_portal_near  = near_r
    #         p_obj.ls3d_portal_far   = far_r
    #        # p_obj.ls3d_portal_normal = normal
    #        # p_obj.ls3d_portal_dot    = dot

    #         # Geometry
    #         if len(p_verts) >= 3:
    #             pbm = bmesh.new()
    #             for v in p_verts:
    #                 pbm.verts.new(v)
    #             pbm.verts.ensure_lookup_table()
    #             try:
    #                 pbm.faces.new(pbm.verts)
    #             except:
    #                 pass
    #             pbm.to_mesh(p_mesh)
    #             pbm.free()

    def deserialize_occluder(self, f, obj, pos, rot, scl):
        # -------------------------------------------------
        # Occluder payload = geometry ONLY
        # Frame transform & parenting are handled elsewhere
        # -------------------------------------------------

        data = f.read(8)
        if len(data) < 8:
            print(f"LS3D Warning: Occluder '{obj.name}' has no geometry.")
            return

        num_verts, num_faces = struct.unpack("<2I", data)

        mesh = obj.data
        mesh.clear_geometry()

        # -------------------------------------------------
        # 1. READ VERTICES (LOCAL SPACE)
        # Mafia (X,Y,Z) - Blender (X,Z,Y)
        # -------------------------------------------------
        verts = []
        for _ in range(num_verts):
            x, y, z = struct.unpack("<3f", f.read(12))
            verts.append((x, z, y))

        # -------------------------------------------------
        # 2. READ FACES (SWAP WINDING)
        # -------------------------------------------------
        faces = []
        for _ in range(num_faces):
            a, b, c = struct.unpack("<3H", f.read(6))
            faces.append((a, c, b))

        mesh.from_pydata(verts, [], faces)
        mesh.update()

    def deserialize_billboard(self, f, obj):
        axis = struct.unpack("<I", f.read(4))[0]
        axis_mode = struct.unpack("<?", f.read(1))[0]
        
        if not axis_mode:
            obj.rot_mode = '1'
            obj.rot_axis = '2'  # Default to Z for all axes
        else:
            obj.rot_mode = '2'
            if axis == 0:
                obj.rot_axis = '1'  # X
            elif axis == 1:
                obj.rot_axis = '2'  # Mafia Y (up) -> Blender Z (up)
            elif axis == 2:
                obj.rot_axis = '3'  # Mafia Z -> Blender Y
            else:
                obj.rot_axis = '2'  # Default to Z

    def deserialize_mirror(self, f, obj):
        # --- 1. Min / Max (AABB, Mafia space) ---
        min_raw = struct.unpack("<3f", f.read(12))
        max_raw = struct.unpack("<3f", f.read(12))

        # Convert: Mafia(X, Z, Y) -> Blender(X, Y, Z)
        obj.bbox_min = (min_raw[0], min_raw[2], min_raw[1])
        obj.bbox_max = (max_raw[0], max_raw[2], max_raw[1])

        # --- 2. Center + Radius ---
        # Skip these, we recalculate them on export
        f.read(16) 

        # --- 3. Viewbox Matrix ---
        # Read 16 floats (Row-Major: X, Y, Z, Pos)
        raw = struct.unpack("<16f", f.read(64))

        # MATRIX RECONSTRUCTION
        # We must build the Blender matrix by mapping 4DS ROWS to Blender COLUMNS.
        #
        # 4DS Input (Row-Major):
        # Row 0 (X Axis): [0, 1, 2, _]
        # Row 1 (Y Axis): [4, 5, 6, _]  (Mafia Up)
        # Row 2 (Z Axis): [8, 9, 10, _] (Mafia Fwd)
        # Row 3 (Pos):    [12, 13, 14, _]
        #
        # Blender Output (Column-Major Logic):
        # Col 0 (X Axis): Matches 4DS Row 0. Swap Y/Z.
        # Col 1 (Y Axis): Matches 4DS Row 2 (Fwd). Swap Y/Z.
        # Col 2 (Z Axis): Matches 4DS Row 1 (Up). Swap Y/Z.
        # Col 3 (Pos):    Matches 4DS Row 3. Swap Y/Z.

        m_blender = Matrix((
            (raw[0],  raw[8],  raw[4],  raw[12]), # Blender Row 0 (X components)
            (raw[2],  raw[10], raw[6],  raw[14]), # Blender Row 1 (Y components)
            (raw[1],  raw[9],  raw[5],  raw[13]), # Blender Row 2 (Z components)
            (0.0,     0.0,     0.0,     1.0),     # Blender Row 3 (Homogeneous)
        ))

        # --- 4. Properties ---
        obj.ls3d_mirror_color = struct.unpack("<3f", f.read(12))
        obj.ls3d_mirror_range = struct.unpack("<f", f.read(4))[0]

        # --- 5. Geometry ---
        num_verts = struct.unpack("<I", f.read(4))[0]
        num_faces = struct.unpack("<I", f.read(4))[0]

        bm = bmesh.new()
        verts = []

        # Read Vertices
        for _ in range(num_verts):
            vx, vy, vz = struct.unpack("<3f", f.read(12))
            # Swap Y/Z
            verts.append(bm.verts.new((vx, vz, vy)))

        bm.verts.ensure_lookup_table()

        # Read Faces
        for _ in range(num_faces):
            i0, i1, i2 = struct.unpack("<3H", f.read(6))
            try:
                # Winding: 4DS(0,2,1) -> Blender(0,1,2)
                bm.faces.new((verts[i0], verts[i2], verts[i1]))
            except ValueError:
                pass 

        bm.to_mesh(obj.data)
        bm.free()

        # --- 6. Create Viewbox Empty ---
        vb_name = f"{obj.name}_viewbox"
        vb = bpy.data.objects.new(vb_name, None)
        vb.empty_display_type = 'CUBE'
        
        # Max BoxSize 2.0 = Radius 1.0. Scale comes from the matrix.
        vb.empty_display_size = 1.0 
        
        bpy.context.collection.objects.link(vb)
        vb.parent = obj
        
        # Apply the converted Matrix
        vb.matrix_local = m_blender

    def deserialize_lensflare(self, f, name, pos, rot, scl):
        """
        Deserialize Mafia lens flare (VISUAL_LENSFLARE).
        Represented as a sphere EMPTY with glow data.
        """

        obj = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(obj)

        obj.empty_display_type = 'SPHERE'
        obj.empty_display_size = 0.05
        obj.location = pos
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = rot
        obj.scale = scl

        # ---- glow data ----
        num_glows = struct.unpack("<B", f.read(1))[0]

        obj.ls3d_glow_position = 0.0
        obj.ls3d_glow_material = None

        for i in range(num_glows):
            glow_pos = struct.unpack("<f", f.read(4))[0]
            mat_index = struct.unpack("<H", f.read(2))[0]

            if i == 0:
                obj.ls3d_glow_position = glow_pos
                if 0 <= mat_index < len(self.materials):
                    obj.ls3d_glow_material = self.materials[mat_index]

        return obj

class Export4DS(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.4ds"
    bl_label = "Export 4DS"
    filename_ext = ".4ds"
    filter_glob = StringProperty(default="*.4ds", options={"HIDDEN"})
    
    def execute(self, context):
        filepath = self.filepath
        filename = os.path.basename(filepath)

        log_clear(f"Exporting: {filename}")
        log_info(f"Exporting {filename} ...")

        wm = context.window_manager
        wm.progress_begin(0, 100)
        wm.progress_update(1)

        # Always export the entire scene. Using context.selected_objects when
        # something is selected silently excludes every unselected object, making
        # newly added geometry invisible in-game even though it looks fine in Blender.
        objects = list(context.scene.objects)
        log_info(f"Scene objects: {len(objects)}")

        exporter = The4DSExporter(
            filepath, objects, operator=self,
            progress_fn=lambda p: wm.progress_update(p),
        )
        try:
            filepath = exporter.prepare_for_export()
        except RuntimeError:
            # Errors already logged via add_error / raise_if_errors
            if not exporter.errors:
                log_error("Export failed (unknown error)")
            _set_log_title(f"Export FAILED: {filename}")
            wm.progress_end()
            _show_log()
            return {'CANCELLED'}
        except Exception as e:
            log_error(f"Export failed: {e}")
            _set_log_title(f"Export FAILED: {filename}")
            wm.progress_end()
            _show_log()
            return {'CANCELLED'}

        log_separator()
        log_success(f"Export complete: {filename}")
        _set_log_title(f"Export OK: {filename}")
        wm.progress_end()
        _show_log()
        return {'FINISHED'}
    
class Import4DS(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.4ds"
    bl_label = "Import 4DS"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".4ds"
    filter_glob = StringProperty(default="*.4ds", options={"HIDDEN"})

    def execute(self, context):
        filename = os.path.basename(self.filepath)

        log_clear(f"Importing: {filename}")
        log_info(f"Importing {filename} ...")

        wm = context.window_manager
        wm.progress_begin(0, 100)
        wm.progress_update(1)

        try:
            importer = The4DSImporter(self.filepath)
            importer.import_file()
        except Exception as e:
            log_error(f"Import failed: {e}")
            _set_log_title(f"Import FAILED: {filename}")
            wm.progress_end()
            _show_log()
            return {'CANCELLED'}

        wm.progress_update(90)

        for obj in context.scene.objects:
            if obj.ls3d_frame_type == '0':
                obj.ls3d_frame_type = detect_initial_frame_type(obj)
            ls3d_update_viewport_display(obj)

        log_separator()
        log_success(f"Import complete: {filename}")
        _set_log_title(f"Import OK: {filename}")
        wm.progress_end()
        _show_log()
        return {"FINISHED"}
    
def menu_func_import(self, context):
    self.layout.operator(Import4DS.bl_idname, text="4DS Mafia Model File (.4ds)")

def menu_func_export(self, context):
    self.layout.operator(Export4DS.bl_idname, text="4DS Mafia Model File (.4ds)")

# --- PROPERTY HELPER FUNCTIONS ---

def get_flag_mask(self, prop_name, mask):
    """Returns True if mask is set (unsigned-safe)."""
    return (getattr(self, prop_name, 0) & mask) != 0

def set_flag_mask(self, value, prop_name, mask):
    """Sets/clears mask safely on signed 32-bit storage."""
    current_signed = getattr(self, prop_name, 0)
    current_unsigned = current_signed & 0xFFFFFFFF

    if value:
        new_unsigned = current_unsigned | mask
    else:
        new_unsigned = current_unsigned & ~mask

    # convert back to signed
    if new_unsigned >= 0x80000000:
        new_signed = new_unsigned - 0x100000000
    else:
        new_signed = new_unsigned

    setattr(self, prop_name, int(new_signed))

def make_getter(prop_name, mask):
    return lambda self: get_flag_mask(self, prop_name, mask)

def make_setter(prop_name, mask):
    return lambda self, value: set_flag_mask(self, value, prop_name, mask)

# --- STRING PROPERTY HELPERS (For Raw Int Display) ---

def get_mat_flags_unsigned(self):
    return f"0x{self.ls3d_material_flags & 0xFFFFFFFF:08X}"

def set_mat_flags_unsigned(self, value):
    try:
        val = int(value, 16) if value.startswith(('0x', '0X')) else int(value, 0)
        val = val & 0xFFFFFFFF
        self.ls3d_material_flags = val if val < 0x80000000 else val - 0x100000000
    except ValueError:
        pass
    
# --- SECTOR FLAG UI HELPERS ---

def get_sector_flags1_unsigned(self):
    return f"0x{self.ls3d_sector_flags1 & 0xFFFFFFFF:08X}"

def set_sector_flags1_unsigned(self, value):
    try:
        val = int(value, 16) if value.startswith(('0x', '0X')) else int(value, 0)
        val = val & 0xFFFFFFFF
        self.ls3d_sector_flags1 = val if val < 0x80000000 else val - 0x100000000
    except ValueError:
        pass

def get_sector_flags2_unsigned(self):
    return f"0x{self.ls3d_sector_flags2 & 0xFFFFFFFF:08X}"

def set_sector_flags2_unsigned(self, value):
    try:
        val = int(value, 16) if value.startswith(('0x', '0X')) else int(value, 0)
        val = val & 0xFFFFFFFF
        self.ls3d_sector_flags2 = val if val < 0x80000000 else val - 0x100000000
    except ValueError:
        pass

# --- GLOBAL CONSTANTS FOR ENUM ---
LS3D_FRAME_ITEMS = (
    ('1', "Visual", "Standard Mesh (FRAME_VISUAL)"),
    ('5', "Sector", "Sector/Portal (FRAME_SECTOR)"),
    ('6', "Dummy", "Helper/Mount Point (FRAME_DUMMY)"),
    ('7', "Target", "Target/LookAt (FRAME_TARGET)"),
    ('9', "Model", "External Model Ref (FRAME_MODEL)"),
    ('10', "Joint", "Bone/Joint (FRAME_JOINT)"),
    ('12', "Occluder", "Visibility Occluder (FRAME_OCCLUDER)"),
)

# --- PROPERTY CALLBACKS ---

def detect_initial_frame_type(obj):
    """
    Returns the default Frame Type ID (String) based on the Blender Object Type.
    """
    # 1. Armatures are always Joints
    if obj.type == 'ARMATURE':
        return str(FRAME_JOINT) # '10'

    # 2. Empties
    elif obj.type == 'EMPTY':
        if obj.empty_display_type == 'PLAIN_AXES':
            return str(FRAME_TARGET) # '7'
        else:
            return str(FRAME_DUMMY) # '6'

    # 3. Meshes
    elif obj.type == 'MESH':
        # Default to Visual
        return str(FRAME_VISUAL) # '1'

    # 4. Fallback
    return str(FRAME_DUMMY) # '6'

def frame_type_items(self, context):
    items = []

    # ---------------- MESH ----------------
    if self.type == 'MESH':
        items = [
            (str(FRAME_VISUAL),   "Visual",   ""),
            (str(FRAME_SECTOR),   "Sector",   ""),
            (str(FRAME_OCCLUDER), "Occluder", ""),
        ]

    # ---------------- EMPTY ----------------
    elif self.type == 'EMPTY':

        if self.empty_display_type == 'CUBE':
            items = [
                (str(FRAME_DUMMY),  "Dummy",  ""),
            ]

        elif self.empty_display_type == 'SPHERE':
            items = [
                (str(FRAME_VISUAL), "Visual", ""),
            ]

        elif self.empty_display_type == 'PLAIN_AXES':
            items = [
                (str(FRAME_TARGET), "Target", ""),
            ]

    # ---------------- ARMATURE ----------------
    elif self.type == 'ARMATURE':
        items = [
            (str(FRAME_JOINT), "Joint", ""),
        ]

    # Safety fallback
    if not items:
        items = [(str(FRAME_VISUAL), "Visual", "")]

    return items

def visual_type_items(self, context):
    items = []

    frame_type = int(self.ls3d_frame_type)

    if frame_type != FRAME_VISUAL:
        return [(str(VISUAL_OBJECT), "Standard", "")]

    if self.type == 'MESH':
        items = [
            (str(VISUAL_OBJECT),       "Object",       ""),
            (str(VISUAL_SINGLEMESH),  "Single Mesh",  ""),
            (str(VISUAL_SINGLEMORPH), "Single Morph", ""),
            (str(VISUAL_MORPH),       "Morph",        ""),
            (str(VISUAL_BILLBOARD),   "Billboard",    ""),
            (str(VISUAL_MIRROR),      "Mirror",       ""),
        ]

    elif self.type == 'EMPTY' and self.empty_display_type == 'SPHERE':
        items = [
            (str(VISUAL_LENSFLARE), "Lens Flare", ""),
        ]

    if not items:
        items = [(str(VISUAL_OBJECT), "Standard", "")]

    return items

import re

# ──────────────────────────────────────────────────────────────────────────────
# MATERIAL NODE LABELS — used to find nodes without a full rebuild
# ──────────────────────────────────────────────────────────────────────────────
_NL_DIFFUSE_TEX     = "LS3D_DIFFUSE_TEX"
_NL_ALPHA_TEX       = "LS3D_ALPHA_TEX"
_NL_ENV_COORD       = "LS3D_ENV_COORD"
_NL_ENV_MAP_SPHERE  = "LS3D_ENV_MAP_SPHERE"
_NL_ENV_IMG_SPHERE  = "LS3D_ENV_IMG_SPHERE"
_NL_ENV_MAP_DETY    = "LS3D_ENV_MAP_DETY"
_NL_ENV_IMG_DETY    = "LS3D_ENV_IMG_DETY"
_NL_ENV_MAP_DETZ    = "LS3D_ENV_MAP_DETZ"
_NL_ENV_IMG_DETZ    = "LS3D_ENV_IMG_DETZ"
_NL_ENV_COMBINE_1   = "LS3D_ENV_COMBINE_1"
_NL_ENV_COMBINE_2   = "LS3D_ENV_COMBINE_2"
_NL_ENV_MIX_OVERLAY = "LS3D_ENV_MIX_OVERLAY"
_NL_ENV_MIX_MULT    = "LS3D_ENV_MIX_MULT"
_NL_ENV_MIX_ADD     = "LS3D_ENV_MIX_ADD"
_NL_BSDF            = "LS3D_BSDF"
_NL_OUT             = "LS3D_OUTPUT"
_NL_COLOR_KEY_SEP_D = "LS3D_COLOR_KEY_SEP_D"
_NL_COLOR_KEY_CMP_R = "LS3D_COLOR_KEY_CMP_R"
_NL_COLOR_KEY_CMP_G = "LS3D_COLOR_KEY_CMP_G"
_NL_COLOR_KEY_CMP_B = "LS3D_COLOR_KEY_CMP_B"
_NL_COLOR_KEY_MUL_A = "LS3D_COLOR_KEY_MUL_A"
_NL_COLOR_KEY_MUL_B = "LS3D_COLOR_KEY_MUL_B"
_NL_COLOR_KEY_INV   = "LS3D_COLOR_KEY_INV"
_NL_ADDITIVE_BW     = "LS3D_ADDITIVE_BW"
_NL_DIFF_COORD      = "LS3D_DIFF_COORD"
_NL_DIFF_SEP        = "LS3D_DIFF_SEP"
_NL_DIFF_CLAMP_U    = "LS3D_DIFF_CLAMP_U"
_NL_DIFF_CLAMP_V    = "LS3D_DIFF_CLAMP_V"
_NL_DIFF_COMB       = "LS3D_DIFF_COMB"
_NL_OPACITY_VAL     = "LS3D_OPACITY_VAL"
_NL_OPACITY_MUL     = "LS3D_OPACITY_MUL"

def ls3d_rebuild_material_nodes(mat):
    if mat is None:
        return

    mat.use_nodes = True
    tree  = mat.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    def N(typ, label, x, y):
        n = nodes.new(typ); n.label = label; n.location = (x, y); return n

    # ── Output + BSDF ─────────────────────────────────────────────────────────
    out  = N('ShaderNodeOutputMaterial', _NL_OUT,  900, 0)
    bsdf = N('ShaderNodeBsdfPrincipled', _NL_BSDF, 550, 0)
    try:   bsdf.inputs["Specular IOR Level"].default_value = 0.0
    except:
        try: bsdf.inputs["Specular"].default_value = 0.0
        except: pass
    try:   bsdf.inputs["Roughness"].default_value = 1.0
    except: pass
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # ── Env projection chains — always present, image assigned by sync ────────
    # Three independent chains (sphere, top-down, front-back) are always built.
    # ls3d_sync_material_flags assigns mat.ls3d_env_tex to the active ones and
    # None to the rest, so inactive chains output black and add nothing.
    coord = N('ShaderNodeTexCoord', _NL_ENV_COORD, -1550, -200)

    # Sphere (MTL_ENV_PROJY) — Reflection vector
    map_sph = N('ShaderNodeMapping',  _NL_ENV_MAP_SPHERE, -1300,  50)
    img_sph = N('ShaderNodeTexImage', _NL_ENV_IMG_SPHERE, -1050,  50)
    img_sph.projection = 'SPHERE'
    links.new(coord.outputs["Reflection"], map_sph.inputs["Vector"])
    links.new(map_sph.outputs["Vector"],   img_sph.inputs["Vector"])

    # Detail-Y (MTL_ENV_DETAILY) — flat from Z axis, object X/Y → U/V
    map_dy = N('ShaderNodeMapping',  _NL_ENV_MAP_DETY, -1300, -250)
    img_dy = N('ShaderNodeTexImage', _NL_ENV_IMG_DETY, -1050, -250)
    img_dy.projection = 'FLAT'; img_dy.extension = 'REPEAT'
    links.new(coord.outputs["Object"], map_dy.inputs["Vector"])
    links.new(map_dy.outputs["Vector"], img_dy.inputs["Vector"])

    # Detail-Z (MTL_ENV_DETAILZ) — flat from Y axis, 90° X rotation → X/Z → U/V
    map_dz = N('ShaderNodeMapping',  _NL_ENV_MAP_DETZ, -1300, -550)
    map_dz.inputs["Rotation"].default_value = (math.pi / 2.0, 0.0, 0.0)
    img_dz = N('ShaderNodeTexImage', _NL_ENV_IMG_DETZ, -1050, -550)
    img_dz.projection = 'FLAT'; img_dz.extension = 'REPEAT'
    links.new(coord.outputs["Object"], map_dz.inputs["Vector"])
    links.new(map_dz.outputs["Vector"], img_dz.inputs["Vector"])

    # Combine all three with ADD
    c1 = N('ShaderNodeMixRGB', _NL_ENV_COMBINE_1, -780, -100)
    c1.blend_type = 'ADD'; c1.inputs['Fac'].default_value = 1.0
    links.new(img_sph.outputs["Color"], c1.inputs["Color1"])
    links.new(img_dy.outputs["Color"],  c1.inputs["Color2"])

    c2 = N('ShaderNodeMixRGB', _NL_ENV_COMBINE_2, -580, -100)
    c2.blend_type = 'ADD'; c2.inputs['Fac'].default_value = 1.0
    links.new(c1.outputs["Color"],      c2.inputs["Color1"])
    links.new(img_dz.outputs["Color"],  c2.inputs["Color2"])

    # ── Three blend-mode mix nodes ────────────────────────────────────────────
    env_ov  = N('ShaderNodeMixRGB', _NL_ENV_MIX_OVERLAY, -250, 150)
    env_ov.blend_type = 'MIX'; env_ov.inputs["Fac"].default_value = 0.0
    env_ov.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1.0)
    env_ov.inputs["Color2"].default_value = (0.0, 0.0, 0.0, 1.0)

    env_mul = N('ShaderNodeMixRGB', _NL_ENV_MIX_MULT, 50, 150)
    env_mul.blend_type = 'MIX'; env_mul.inputs["Fac"].default_value = 0.0
    env_mul.inputs["Color2"].default_value = (0.0, 0.0, 0.0, 1.0)

    env_add = N('ShaderNodeMixRGB', _NL_ENV_MIX_ADD, 350, 150)
    env_add.blend_type = 'MIX'; env_add.inputs["Fac"].default_value = 0.0
    env_add.inputs["Color2"].default_value = (0.0, 0.0, 0.0, 1.0)

    # ── Diffuse / Alpha ───────────────────────────────────────────────────────
    diff_n  = N('ShaderNodeTexImage', _NL_DIFFUSE_TEX, -700,  400)
    alpha_n = N('ShaderNodeTexImage', _NL_ALPHA_TEX,   -700, -900)

    diff_coord = N('ShaderNodeTexCoord',    _NL_DIFF_COORD,   -1400, 400)
    diff_sep   = N('ShaderNodeSeparateXYZ', _NL_DIFF_SEP,     -1200, 400)
    diff_cu    = N('ShaderNodeClamp',       _NL_DIFF_CLAMP_U, -1000, 450)
    diff_cv    = N('ShaderNodeClamp',       _NL_DIFF_CLAMP_V, -1000, 350)
    diff_comb  = N('ShaderNodeCombineXYZ',  _NL_DIFF_COMB,     -800, 400)

    links.new(diff_coord.outputs["UV"],   diff_sep.inputs["Vector"])
    links.new(diff_sep.outputs["X"],      diff_cu.inputs["Value"])
    links.new(diff_sep.outputs["Y"],      diff_cv.inputs["Value"])
    links.new(diff_cu.outputs["Result"],  diff_comb.inputs["X"])
    links.new(diff_cv.outputs["Result"],  diff_comb.inputs["Y"])
    links.new(diff_comb.outputs["Vector"], diff_n.inputs["Vector"])

    additive_bw = N('ShaderNodeRGBToBW', _NL_ADDITIVE_BW, -350, 400)
    links.new(diff_n.outputs["Color"], additive_bw.inputs["Color"])

    if mat.ls3d_diffuse_tex: diff_n.image = mat.ls3d_diffuse_tex
    flags_u = mat.ls3d_material_flags & 0xFFFFFFFF
    diff_n.interpolation = 'Closest' if (flags_u & MTL_ALPHA_COLORKEY) else 'Linear'

    if mat.ls3d_alpha_tex:
        alpha_n.image = mat.ls3d_alpha_tex
        try: alpha_n.image.colorspace_settings.name = 'Non-Color'
        except: pass

    # ── Color key ─────────────────────────────────────────────────────────────
    ck_sep   = N('ShaderNodeSeparateColor', _NL_COLOR_KEY_SEP_D, -1050, 700)
    thr = 0.005
    ck_cmp_r = N('ShaderNodeMath', _NL_COLOR_KEY_CMP_R, -850, 800)
    ck_cmp_r.operation = 'COMPARE'; ck_cmp_r.inputs[2].default_value = thr
    ck_cmp_g = N('ShaderNodeMath', _NL_COLOR_KEY_CMP_G, -850, 660)
    ck_cmp_g.operation = 'COMPARE'; ck_cmp_g.inputs[2].default_value = thr
    ck_cmp_b = N('ShaderNodeMath', _NL_COLOR_KEY_CMP_B, -850, 520)
    ck_cmp_b.operation = 'COMPARE'; ck_cmp_b.inputs[2].default_value = thr
    ck_mul_a = N('ShaderNodeMath', _NL_COLOR_KEY_MUL_A, -650, 730); ck_mul_a.operation = 'MULTIPLY'
    ck_mul_b = N('ShaderNodeMath', _NL_COLOR_KEY_MUL_B, -500, 730); ck_mul_b.operation = 'MULTIPLY'
    ck_inv   = N('ShaderNodeMath', _NL_COLOR_KEY_INV,   -350, 730)
    ck_inv.operation = 'SUBTRACT'; ck_inv.inputs[0].default_value = 1.0

    # was: key_color = ls3d_read_bmp_color_key(mat.ls3d_diffuse_tex) or (0.0, 0.0, 0.0)
    key_color = tuple(mat.ls3d_color_key) if (mat.ls3d_material_flags & 0xFFFFFFFF & MTL_ALPHA_COLORKEY) else (0.0, 0.0, 0.0)
    ck_cmp_r.inputs[1].default_value = key_color[0]
    ck_cmp_g.inputs[1].default_value = key_color[1]
    ck_cmp_b.inputs[1].default_value = key_color[2]

    # ── Static wires ──────────────────────────────────────────────────────────
    env_out = c2.outputs["Color"]
    links.new(diff_n.outputs["Color"], env_ov.inputs["Color1"])
    links.new(env_out,                 env_ov.inputs["Color2"])
    links.new(env_out,                 env_mul.inputs["Color2"])
    links.new(env_out,                 env_add.inputs["Color2"])
    links.new(env_ov.outputs["Color"],  env_mul.inputs["Color1"])
    links.new(env_mul.outputs["Color"], env_add.inputs["Color1"])
    links.new(env_add.outputs["Color"], bsdf.inputs["Base Color"])

    links.new(diff_n.outputs["Color"],   ck_sep.inputs[0])
    links.new(ck_sep.outputs["Red"],     ck_cmp_r.inputs[0])
    links.new(ck_sep.outputs["Green"],   ck_cmp_g.inputs[0])
    links.new(ck_sep.outputs["Blue"],    ck_cmp_b.inputs[0])
    links.new(ck_cmp_r.outputs["Value"], ck_mul_a.inputs[0])
    links.new(ck_cmp_g.outputs["Value"], ck_mul_a.inputs[1])
    links.new(ck_mul_a.outputs["Value"], ck_mul_b.inputs[0])
    links.new(ck_cmp_b.outputs["Value"], ck_mul_b.inputs[1])
    links.new(ck_mul_b.outputs["Value"], ck_inv.inputs[1])

    opacity_val = N('ShaderNodeValue', _NL_OPACITY_VAL, -150, -50)
    opacity_val.outputs[0].default_value = mat.ls3d_opacity

    opacity_mul = N('ShaderNodeMath', _NL_OPACITY_MUL, 50, -50)
    opacity_mul.operation = 'MULTIPLY'
    opacity_mul.inputs[0].default_value = 1.0  # alpha source default (fully opaque)
    links.new(opacity_val.outputs[0], opacity_mul.inputs[1])
    links.new(opacity_mul.outputs["Value"], bsdf.inputs["Alpha"])

    # ── Emission ──────────────────────────────────────────────────────────────
    emi = mat.ls3d_emission_color
    try:    bsdf.inputs["Emission Color"].default_value = (emi[0], emi[1], emi[2], 1.0); bsdf.inputs["Emission Strength"].default_value = 1.0
    except:
        try: bsdf.inputs["Emission"].default_value      = (emi[0], emi[1], emi[2], 1.0); bsdf.inputs["Emission Strength"].default_value = 1.0
        except: pass

    ls3d_sync_material_flags(mat)

def ls3d_sync_material_flags(mat):
    if mat is None or not mat.use_nodes:
        return

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    if not _find_node(nodes, _NL_BSDF):
        ls3d_rebuild_material_nodes(mat)
        return

    flags        = mat.ls3d_material_flags & 0xFFFFFFFF
    do_sphere    = bool(flags & MTL_ENV_PROJY)
    do_detaily   = bool(flags & MTL_ENV_DETAILY)
    do_detailz   = bool(flags & MTL_ENV_DETAILZ)
    if not do_sphere and not do_detaily and not do_detailz:
        do_sphere = True

    diff_enable      = bool(flags & MTL_DIFFUSE_ENABLE)
    diff_doublesided = bool(flags & MTL_DIFFUSE_DOUBLESIDED)
    alpha_enable     = bool(flags & MTL_ALPHA_ENABLE)
    alpha_tex_flag   = bool(flags & MTL_ALPHATEX)
    alpha_colorkey   = bool(flags & MTL_ALPHA_COLORKEY)
    alpha_additive   = bool(flags & MTL_ALPHA_ADDITIVE)
    alpha_in_tex     = bool(flags & MTL_ALPHA_IN_TEX)
    env_enable       = bool(flags & MTL_ENV_ENABLE)
    env_overlay      = bool(flags & MTL_ENV_OVERLAY)
    env_multiply     = bool(flags & MTL_ENV_MULTIPLY)
    env_additive     = bool(flags & MTL_ENV_ADDITIVE)

    opacity    = mat.ls3d_opacity
    env_amount = mat.ls3d_env_amount

    bsdf_n   = _find_node(nodes, _NL_BSDF)
    diff_n   = _find_node(nodes, _NL_DIFFUSE_TEX)
    alpha_n  = _find_node(nodes, _NL_ALPHA_TEX)
    img_sph  = _find_node(nodes, _NL_ENV_IMG_SPHERE)
    img_dy   = _find_node(nodes, _NL_ENV_IMG_DETY)
    img_dz   = _find_node(nodes, _NL_ENV_IMG_DETZ)
    env_ov   = _find_node(nodes, _NL_ENV_MIX_OVERLAY)
    env_mul  = _find_node(nodes, _NL_ENV_MIX_MULT)
    env_add  = _find_node(nodes, _NL_ENV_MIX_ADD)
    ck_cmp_r = _find_node(nodes, _NL_COLOR_KEY_CMP_R)
    ck_cmp_g = _find_node(nodes, _NL_COLOR_KEY_CMP_G)
    ck_cmp_b = _find_node(nodes, _NL_COLOR_KEY_CMP_B)
    ck_inv   = _find_node(nodes, _NL_COLOR_KEY_INV)
    additive_bw = _find_node(nodes, _NL_ADDITIVE_BW)
    diff_cu = _find_node(nodes, _NL_DIFF_CLAMP_U)
    diff_cv = _find_node(nodes, _NL_DIFF_CLAMP_V)
    opacity_val = _find_node(nodes, _NL_OPACITY_VAL)
    opacity_mul = _find_node(nodes, _NL_OPACITY_MUL)

    def unlink_input(node, name):
        if node and name in node.inputs:
            for lnk in list(node.inputs[name].links): links.remove(lnk)

    def ensure_link(from_sock, to_node, to_name):
        if not (from_sock and to_node and to_name in to_node.inputs): return
        sock = to_node.inputs[to_name]
        for lnk in sock.links:
            if lnk.from_socket is from_sock: return
            links.remove(lnk)
        links.new(from_sock, sock)

    def set_transparency(mode):
        try:
            mat.surface_render_method = 'BLENDED' if mode == 'BLEND' else 'DITHERED'
        except: pass
        try: mat.blend_method = mode
        except: pass
        if mode == 'CLIP':
            try: mat.alpha_threshold = 0.5
            except: pass

    # ── Textures ──────────────────────────────────────────────────────────────
    if diff_n:
        diff_n.image = mat.ls3d_diffuse_tex or None
        diff_n.interpolation = 'Closest' if alpha_colorkey else 'Linear'
    if alpha_n:
        alpha_n.image = mat.ls3d_alpha_tex or None
        if alpha_n.image:
            try: alpha_n.image.colorspace_settings.name = 'Non-Color'
            except: pass

    env_tex = mat.ls3d_env_tex if (env_enable and mat.ls3d_env_tex) else None
    if img_sph: img_sph.image = env_tex if do_sphere  else None
    if img_dy:  img_dy.image  = env_tex if do_detaily else None
    if img_dz:  img_dz.image  = env_tex if do_detailz else None

    disable_u = bool(flags & MTL_DISABLE_U_TILING)
    disable_v = bool(flags & MTL_DISABLE_V_TILING)
    if diff_cu:
        diff_cu.inputs["Min"].default_value = 0.0     if disable_u else -10000.0
        diff_cu.inputs["Max"].default_value = 1.0     if disable_u else  10000.0
    if diff_cv:
        diff_cv.inputs["Min"].default_value = 0.0     if disable_v else -10000.0
        diff_cv.inputs["Max"].default_value = 1.0     if disable_v else  10000.0

    # ── Backface culling ──────────────────────────────────────────────────────
    try: mat.use_backface_culling = not diff_doublesided
    except: pass

    # ── Diffuse visibility ────────────────────────────────────────────────────
    if diff_n:
        if diff_enable and mat.ls3d_diffuse_tex:
            ensure_link(diff_n.outputs["Color"], env_ov, "Color1")
        else:
            unlink_input(env_ov, "Color1")
            if env_ov: env_ov.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1.0)

    # ── Color key ─────────────────────────────────────────────────────────────
    if alpha_colorkey and ck_cmp_r and ck_cmp_g and ck_cmp_b:
        key_color = tuple(mat.ls3d_color_key)
        ck_cmp_r.inputs[1].default_value = key_color[0]
        ck_cmp_g.inputs[1].default_value = key_color[1]
        ck_cmp_b.inputs[1].default_value = key_color[2]

    # ── Environment blend mode ────────────────────────────────────────────────
    active = env_enable and bool(mat.ls3d_env_tex)

    def set_env(ov_type, ov_fac, mul_type, mul_fac, add_type, add_fac):
        if env_ov:  env_ov.blend_type  = ov_type;  env_ov.inputs["Fac"].default_value  = ov_fac
        if env_mul: env_mul.blend_type = mul_type; env_mul.inputs["Fac"].default_value = mul_fac
        if env_add: env_add.blend_type = add_type; env_add.inputs["Fac"].default_value = add_fac

    if   not active:                    set_env('MIX', 0.0,           'MIX', 0.0, 'MIX', 0.0)
    elif env_multiply and env_overlay:  set_env('OVERLAY', env_amount, 'MULTIPLY', 0.0, 'MIX', 0.0)
    elif env_additive and env_overlay:  set_env('OVERLAY', env_amount, 'MIX', 0.0, 'ADD', env_amount)
    elif env_additive and env_multiply: set_env('OVERLAY', env_amount, 'MIX', 0.0, 'ADD', env_amount)
    elif env_multiply:                  set_env('MIX', 0.0,           'MIX', 1.0, 'MIX', 0.0)
    elif env_additive:                  set_env('MIX', 0.0,           'MIX', 0.0, 'OVERLAY', env_amount)
    elif env_overlay:                   set_env('MIX', env_amount,    'MIX', 0.0, 'MIX', 0.0)
    else:                               set_env('MIX', 0.0,           'MIX', 0.0, 'MIX', 0.0)

    # ── Emission ──────────────────────────────────────────────────────────────
    if bsdf_n:
        emi = mat.ls3d_emission_color
        try:    bsdf_n.inputs["Emission Color"].default_value = (emi[0], emi[1], emi[2], 1.0); bsdf_n.inputs["Emission Strength"].default_value = 1.0
        except:
            try: bsdf_n.inputs["Emission"].default_value      = (emi[0], emi[1], emi[2], 1.0); bsdf_n.inputs["Emission Strength"].default_value = 1.0
            except: pass

    # ── Alpha ─────────────────────────────────────────────────────────────────
    # opacity_mul.inputs[0] = alpha source, inputs[1] = opacity scalar
    # Always wire opacity_mul → BSDF Alpha
    if opacity_val: opacity_val.outputs[0].default_value = opacity
    if opacity_mul: ensure_link(opacity_mul.outputs["Value"], bsdf_n, "Alpha")

    # Reset alpha source to 1.0 (fully opaque), then override below
    if opacity_mul: opacity_mul.inputs[0].default_value = 1.0
    unlink_input(opacity_mul, "Value") if opacity_mul else None
    # unlink only the alpha source input (slot 0), not the opacity input (slot 1)
    if opacity_mul:
        for lnk in list(opacity_mul.inputs[0].links):
            links.remove(lnk)

    set_transparency('OPAQUE')

    if alpha_colorkey and diff_n and mat.ls3d_diffuse_tex and ck_inv:
        if opacity_mul: links.new(ck_inv.outputs["Value"], opacity_mul.inputs[0])
        set_transparency('CLIP' if opacity >= 1.0 else 'BLEND')
    elif alpha_enable:
        if alpha_in_tex and diff_n and mat.ls3d_diffuse_tex:
            if opacity_mul: links.new(diff_n.outputs["Alpha"], opacity_mul.inputs[0])
        elif alpha_tex_flag and alpha_n and mat.ls3d_alpha_tex and not alpha_in_tex:
            if opacity_mul: links.new(alpha_n.outputs["Color"], opacity_mul.inputs[0])
        set_transparency('BLEND')

    if alpha_additive and diff_n and mat.ls3d_diffuse_tex and additive_bw:
        if opacity_mul: links.new(additive_bw.outputs["Val"], opacity_mul.inputs[0])
        set_transparency('BLEND')

    if opacity < 1.0:
        set_transparency('BLEND')

def ls3d_update_viewport_display(obj):
    """
    Sets Object Properties → Viewport Display → Color based on frame/visual type.
    Called whenever ls3d_frame_type or visual_type changes, and on import.
    """
    if obj is None:
        return

    # Reset display settings to safe defaults
    obj.display_type   = 'TEXTURED'
    obj.show_wire      = False
    obj.show_all_edges = False
    obj.show_axis      = False

    try:
        frame_type = int(getattr(obj, "ls3d_frame_type", 0))
    except:
        frame_type = 0

    try:
        visual_type = int(getattr(obj, "visual_type", 0))
    except:
        visual_type = 0

    # Enable custom color on the object so our color is actually visible
    obj.color = (1.0, 1.0, 1.0, 1.0)  # reset first

    # --------------------------------------------------
    # SECTOR
    # --------------------------------------------------
    if frame_type == FRAME_SECTOR and obj.type == 'MESH':
        is_portal = (
            obj.parent
            and int(getattr(obj.parent, "ls3d_frame_type", 0)) == FRAME_SECTOR
            and re.search(r"_portal\d+$", obj.name, re.IGNORECASE)
        )
        obj.display_type  = 'WIRE'
        obj.show_wire     = True
        obj.color         = COLOR_FRAME_PORTAL if is_portal else COLOR_FRAME_SECTOR
        if not is_portal:
            obj.show_all_edges = True
        return

    # --------------------------------------------------
    # OCCLUDER
    # --------------------------------------------------
    if frame_type == FRAME_OCCLUDER and obj.type == 'MESH':
        obj.display_type   = 'WIRE'
        obj.show_wire      = True
        obj.show_all_edges = True
        obj.color          = COLOR_FRAME_OCCLUDER
        return

    # --------------------------------------------------
    # DUMMY
    # --------------------------------------------------
    if frame_type == FRAME_DUMMY:
        obj.color = COLOR_FRAME_DUMMY
        return

    # --------------------------------------------------
    # TARGET
    # --------------------------------------------------
    if frame_type == FRAME_TARGET:
        obj.color = COLOR_FRAME_TARGET
        return

    # --------------------------------------------------
    # JOINT (bones handled by armature, but object itself)
    # --------------------------------------------------
    if frame_type == FRAME_JOINT:
        obj.color = COLOR_FRAME_JOINT
        return

    # --------------------------------------------------
    # VISUAL — color by visual sub-type
    # --------------------------------------------------
    if frame_type == FRAME_VISUAL:

        if visual_type == VISUAL_OBJECT:
            obj.color = COLOR_VISUAL_OBJECT

        elif visual_type == VISUAL_LITOBJECT:
            obj.color = COLOR_VISUAL_LITOBJECT

        elif visual_type == VISUAL_SINGLEMESH:
            obj.color = COLOR_VISUAL_SINGLEMESH

        elif visual_type == VISUAL_SINGLEMORPH:
            obj.color = COLOR_VISUAL_SINGLEMORPH

        elif visual_type == VISUAL_BILLBOARD:
            obj.color = COLOR_VISUAL_BILLBOARD

        elif visual_type == VISUAL_MORPH:
            obj.color = COLOR_VISUAL_MORPH

        elif visual_type == VISUAL_LENSFLARE:
            obj.empty_display_type = 'SPHERE'
            obj.empty_display_size = 0.05
            obj.color = COLOR_VISUAL_LENSFLARE

        elif visual_type == VISUAL_MIRROR:
            obj.show_axis = True
            obj.color     = COLOR_VISUAL_MIRROR

        return

    # --------------------------------------------------
    # FALLBACK — unsupported / unknown frame types
    # --------------------------------------------------
    obj.color = (0.5, 0.5, 0.5, 1.0)
# --- REGISTRATION ---

@bpy.app.handlers.persistent
def ls3d_joint_scale_init(scene, depsgraph):
    """Ensure every pose bone in every armature has ls3d_joint_scale."""
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE':
            continue
        for pb in obj.pose.bones:
            if "ls3d_joint_scale" not in pb:
                pb["ls3d_joint_scale"] = (1.0, 1.0, 1.0)

def register():
    # Classes
    bpy.utils.register_class(LS3D_OT_ResultPopup)
    bpy.utils.register_class(LS3D_OT_SetBlendBone)
    bpy.utils.register_class(LS3D_OT_CreateMaterial)
    bpy.utils.register_class(LS3D_AddonPreferences)
    bpy.utils.register_class(The4DSPanelMaterial)
    bpy.utils.register_class(The4DSPanel)
    bpy.utils.register_class(Import4DS)
    bpy.utils.register_class(Export4DS)
    bpy.utils.register_class(LS3DTargetObject)
    bpy.utils.register_class(LS3D_OT_AddTargetObject)
    bpy.utils.register_class(LS3D_OT_RemoveTargetObject)

    # --- MODEL ---
    bpy.types.Scene.ls3d_animated_object_count = IntProperty(name="Animated Objects", description="Number of animated objects (0-255)\nLS3D Will look for the same named 5ds file as this 4ds file (once exported) and use it for the animation.", default=0, min=0, max=255)

    # --- OBJECT PROPERTIES ---
    bpy.types.Object.ls3d_frame_type_override = IntProperty(default=0)

    #bpy.types.Object.ls3d_frame_type = bpy.props.EnumProperty(name="Frame Type", items=frame_type_items, default=0)
    #bpy.types.Object.visual_type = bpy.props.EnumProperty(name="Visual Type", items=visual_type_items, default=0)

    bpy.types.Object.ls3d_frame_type = bpy.props.EnumProperty(name="Frame Type", items=frame_type_items, default=0, update=lambda self, ctx: ls3d_update_viewport_display(self))
    bpy.types.Object.visual_type = bpy.props.EnumProperty(name="Visual Type", items=visual_type_items, default=0, update=lambda self, ctx: ls3d_update_viewport_display(self))
    
    # --- OBJECT CULLING FLAGS ---
    bpy.types.Object.cull_flags = IntProperty(name="Culling Flags", default=0, min=0, max=255)
    bpy.types.Object.cf_enabled = BoolProperty(name="Enabled", description="Object is enabled and visible in game", get=make_getter("cull_flags", CF_ENABLED), set=make_setter("cull_flags", CF_ENABLED))
    bpy.types.Object.cf_unknown2 = BoolProperty(name="Unknown 2", description="", get=make_getter("cull_flags", CF_UNKNOWN2), set=make_setter("cull_flags", CF_UNKNOWN2))
    bpy.types.Object.cf_unknown3 = BoolProperty(name="Unknown 3", description="", get=make_getter("cull_flags", CF_UNKNOWN3), set=make_setter("cull_flags", CF_UNKNOWN3))
    bpy.types.Object.cf_cast_shadow = BoolProperty(name="Cast Shadow", description="Object casts shadow on itself", get=make_getter("cull_flags", CF_CAST_SHADOW), set=make_setter("cull_flags", CF_CAST_SHADOW))
    bpy.types.Object.cf_unknown5 = BoolProperty(name="Unknown 5", description="", get=make_getter("cull_flags", CF_UNKNOWN5), set=make_setter("cull_flags", CF_UNKNOWN5))
    bpy.types.Object.cf_unknown6 = BoolProperty(name="Unknown 6", description="", get=make_getter("cull_flags", CF_UNKNOWN6), set=make_setter("cull_flags", CF_UNKNOWN6))
    bpy.types.Object.cf_hierarchy = BoolProperty(name="Hierarchy ?", description="*Object is a parent and has children objects. If disabled, children will be ignored by LS3D*", get=make_getter("cull_flags", CF_HIERARCHY), set=make_setter("cull_flags", CF_HIERARCHY))
    bpy.types.Object.cf_unknown8 = BoolProperty(name="Unknown 8", description="", get=make_getter("cull_flags", CF_UNKNOWN8), set=make_setter("cull_flags", CF_UNKNOWN8))
    
    # --- VISUAL RENDER FLAGS ---
    bpy.types.Object.render_flags = IntProperty(name="Render Flags 1",  default=0, min=0, max=255)
    bpy.types.Object.render_flags2 = IntProperty(name="Render Flags 2", default=0, min=0, max=255)
    
    bpy.types.Object.rf1_unknown1 = BoolProperty(name="Unknown 1", description="", get=make_getter("render_flags", RF_UNKNOWN1), set=make_setter("render_flags", RF_UNKNOWN1))
    bpy.types.Object.rf1_unknown2 = BoolProperty(name="Unknown 2", description="", get=make_getter("render_flags", RF_UNKNOWN2), set=make_setter("render_flags", RF_UNKNOWN2))
    bpy.types.Object.rf1_unknown3 = BoolProperty(name="Unknown 3", description="", get=make_getter("render_flags", RF_UNKNOWN3), set=make_setter("render_flags", RF_UNKNOWN3))
    bpy.types.Object.rf1_unknown4 = BoolProperty(name="Unknown 4", description="", get=make_getter("render_flags", RF_UNKNOWN4), set=make_setter("render_flags", RF_UNKNOWN4))
    bpy.types.Object.rf1_unknown5 = BoolProperty(name="Unknown 5", description="", get=make_getter("render_flags", RF_UNKNOWN5), set=make_setter("render_flags", RF_UNKNOWN5))
    bpy.types.Object.rf1_unknown6 = BoolProperty(name="Unknown 6", description="", get=make_getter("render_flags", RF_UNKNOWN6), set=make_setter("render_flags", RF_UNKNOWN6))
    bpy.types.Object.rf1_hidemesh = BoolProperty(name="Hide mesh", description="Makes the object mesh invisible, animated mesh gets teleported to XYZ 0 0 0", get=make_getter("render_flags", RF_HIDEMESH), set=make_setter("render_flags", RF_HIDEMESH))
    bpy.types.Object.rf1_noshading = BoolProperty(name="No Shading", description="Object will have no shading, the material will have uniform color all around and it looks like it's in shadow", get=make_getter("render_flags", RF_NOSHADING), set=make_setter("render_flags", RF_NOSHADING))
    
    bpy.types.Object.rf2_zbias = BoolProperty(name="Z-Bias", description="Object acts as a decal (Poster, picture on a wall). Helps with Z-Fighting on flat surfaces by drawing the object above the surface.\nSurface of the object HAS to look at a LOCAL Z AXIS for this flag to work correctly!", get=make_getter("render_flags2", LF_ZBIAS), set=make_setter("render_flags2", LF_ZBIAS))
    bpy.types.Object.rf2_recieve_dynamic_shadow_diffuse = BoolProperty(name="Shadows on Diffuse", description="Object can recieve dynamic shadows on diffuse material (eg. from player or vehicle)", get=make_getter("render_flags2", LF_RECIEVE_DYNAMIC_SHADOW_DIFFUSE), set=make_setter("render_flags2", LF_RECIEVE_DYNAMIC_SHADOW_DIFFUSE))
    bpy.types.Object.rf2_recieve_dynamic_shadow_alpha = BoolProperty(name="Shadows on Alpha", description="Object can recieve dynamic shadows on alpha (transparent) material (eg. from player or vehicle)", get=make_getter("render_flags2", LF_RECIEVE_DYNAMIC_SHADOW_ALPHA), set=make_setter("render_flags2", LF_RECIEVE_DYNAMIC_SHADOW_ALPHA))
    bpy.types.Object.rf2_mirrorable = BoolProperty(name="Mirrorable", description="Object is visible in a Mirror Frame type", get=make_getter("render_flags2", LF_MIRRORABLE), set=make_setter("render_flags2", LF_MIRRORABLE))
    bpy.types.Object.rf2_unknown5 = BoolProperty(name="Unknown 5", description="", get=make_getter("render_flags2", LF_UNKNOWN5), set=make_setter("render_flags2", LF_UNKNOWN5))
    bpy.types.Object.rf2_recieve_projection_diffuse = BoolProperty(name="Projection on Diffuse", description="Object recieves projection textures on diffuse materials (eg. Car headlights, bullet hole decals)", get=make_getter("render_flags2", LF_RECIEVE_PROJECTION_DIFFUSE), set=make_setter("render_flags2", LF_RECIEVE_PROJECTION_DIFFUSE))
    bpy.types.Object.rf2_recieve_projection_alpha = BoolProperty(name="Projection on Alpha", description="Object recieves projection textures on alpha (transparent) materials (eg. Car headlights, bullet hole decals)", get=make_getter("render_flags2", LF_RECIEVE_PROJECTION_ALPHA), set=make_setter("render_flags2", LF_RECIEVE_PROJECTION_ALPHA))
    bpy.types.Object.rf2_no_fog = BoolProperty(name="No Fog", description="Object isn't affected by scene fog", get=make_getter("render_flags2", LF_NO_FOG), set=make_setter("render_flags2", LF_NO_FOG))

    # --- MATERIAL PROPERTIES ---
    bpy.types.Material.ls3d_ambient_color = FloatVectorProperty(subtype='COLOR', min=0.0, max=1.0, default=(0.5, 0.5, 0.5), name="Ambient", update=lambda self, ctx: ls3d_sync_material_flags(self))
    bpy.types.Material.ls3d_diffuse_color = FloatVectorProperty(subtype='COLOR', min=0.0, max=1.0, default=(1, 1, 1), name="Diffuse", update=lambda self, ctx: ls3d_sync_material_flags(self))
    bpy.types.Material.ls3d_emission_color = FloatVectorProperty(subtype='COLOR', min=0.0, max=1.0, default=(0,0,0), name="Emission", update=lambda self, ctx: ls3d_sync_material_flags(self))

    # Change this existing line:
    

    # Add these new properties after the existing material props:
    bpy.types.Material.ls3d_diffuse_tex = bpy.props.PointerProperty(type=bpy.types.Image, name="Diffuse Texture", update=lambda self, ctx: ls3d_rebuild_material_nodes(self))
    bpy.types.Material.ls3d_alpha_tex = bpy.props.PointerProperty(type=bpy.types.Image, name="Alpha Texture", update=lambda self, ctx: ls3d_rebuild_material_nodes(self))
    bpy.types.Material.ls3d_env_tex = bpy.props.PointerProperty(type=bpy.types.Image, name="Environment Texture", update=lambda self, ctx: ls3d_rebuild_material_nodes(self))
    bpy.types.Material.ls3d_env_amount = bpy.props.FloatProperty(name="Env Intensity", default=0.0, min=0.0, max=1.0, update=lambda self, ctx: ls3d_sync_material_flags(self))
    bpy.types.Material.ls3d_opacity = bpy.props.FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, update=lambda self, ctx: ls3d_sync_material_flags(self))

    # Animations
    bpy.types.Material.ls3d_anim_frames = IntProperty(name="Anim Frames", description="Frame count of the Animated Texture (Maximum is 99)", default=0)
    bpy.types.Material.ls3d_anim_period = IntProperty(name="Anim Period", description="Time (in milliseconds) how long the animation frame stays visible before it changes to the next frame", default=0)

    # --- MATERIAL FLAGS ---
    bpy.types.Material.ls3d_material_flags = IntProperty(name="Material Flags", default=0, update=lambda self, ctx: ls3d_sync_material_flags(self))
    bpy.types.Material.ls3d_material_flags_str = StringProperty(name="Raw Flags", description="Raw Unsigned Integer", get=get_mat_flags_unsigned, set=set_mat_flags_unsigned)

    # Boolean accessors
    bpy.types.Material.ls3d_flag_misc_unlit = BoolProperty(name="Unlit", description="Disable lighting calculations? Unknown", get=make_getter("ls3d_material_flags", MTL_MISC_UNLIT), set=make_setter("ls3d_material_flags", MTL_MISC_UNLIT))
    bpy.types.Material.ls3d_flag_env_overlay = BoolProperty(name="Overlay", description="Sets the environment texture to Overlay mode", get=make_getter("ls3d_material_flags", MTL_ENV_OVERLAY), set=make_setter("ls3d_material_flags", MTL_ENV_OVERLAY))
    bpy.types.Material.ls3d_flag_env_multiply = BoolProperty(name="Multiply", description="Sets the environment texture to Multiply mode", get=make_getter("ls3d_material_flags", MTL_ENV_MULTIPLY), set=make_setter("ls3d_material_flags", MTL_ENV_MULTIPLY))
    bpy.types.Material.ls3d_flag_env_additive = BoolProperty(name="Additive", description="Sets the environment texture to Additive mode", get=make_getter("ls3d_material_flags", MTL_ENV_ADDITIVE), set=make_setter("ls3d_material_flags", MTL_ENV_ADDITIVE))
    # bpy.types.Material.ls3d_flag_envtex = BoolProperty(name="Environment Texture", description="Enables Environment texture", get=make_getter("ls3d_material_flags", MTL_ENVTEX), set=make_setter("ls3d_material_flags", MTL_ENVTEX))
    bpy.types.Material.ls3d_flag_env_projy = BoolProperty(name="Global refelction", description="Makes the texture look like a reflection", get=make_getter("ls3d_material_flags", MTL_ENV_PROJY), set=make_setter("ls3d_material_flags", MTL_ENV_PROJY))
    bpy.types.Material.ls3d_flag_env_detaily = BoolProperty(name="Project Y", description="Projects the environment texture on Mafia's Y axis (Up / Down)", get=make_getter("ls3d_material_flags", MTL_ENV_DETAILY), set=make_setter("ls3d_material_flags", MTL_ENV_DETAILY))
    bpy.types.Material.ls3d_flag_env_detailz = BoolProperty(name="Project Z", description="Projects the environment texture on Mafia's Z axis (Front / Back)", get=make_getter("ls3d_material_flags", MTL_ENV_DETAILZ), set=make_setter("ls3d_material_flags", MTL_ENV_DETAILZ))
    
    bpy.types.Material.ls3d_flag_alpha_enable = BoolProperty(name="Alpha Enable", description="Enables alpha effect, if No Alpha Texture is specified, game looks for the Diffuse Texture Name that ends with + and uses it as Alpha Map Texture in LS3D Engine", get=make_getter("ls3d_material_flags", MTL_ALPHA_ENABLE), set=make_setter("ls3d_material_flags", MTL_ALPHA_ENABLE))
    bpy.types.Material.ls3d_flag_disable_u_tiling = BoolProperty(name="Disable U-Tile", description="Disables Horizontal tiling of the texture", get=make_getter("ls3d_material_flags", MTL_DISABLE_U_TILING), set=make_setter("ls3d_material_flags", MTL_DISABLE_U_TILING))
    bpy.types.Material.ls3d_flag_disable_v_tiling = BoolProperty(name="Disable V-Tile", description="Disables Vertical tiling of the texture", get=make_getter("ls3d_material_flags", MTL_DISABLE_V_TILING), set=make_setter("ls3d_material_flags", MTL_DISABLE_V_TILING))
    
    bpy.types.Material.ls3d_flag_diffuse_enable = BoolProperty(name="Use Diffuse Texture", description="Enables the use of Diffuse texture", get=make_getter("ls3d_material_flags", MTL_DIFFUSE_ENABLE), set=make_setter("ls3d_material_flags", MTL_DIFFUSE_ENABLE))
    bpy.types.Material.ls3d_flag_env_enable = BoolProperty(name="Use Environment Texture", description="Enables the use of Environment texture", get=make_getter("ls3d_material_flags", MTL_ENV_ENABLE), set=make_setter("ls3d_material_flags", MTL_ENV_ENABLE))
    bpy.types.Material.ls3d_flag_diffuse_mipmap = BoolProperty(name="MipMap", description="Enables Mip-Mapping for the (Diffuse?) texture", get=make_getter("ls3d_material_flags", MTL_DIFFUSE_MIPMAP), set=make_setter("ls3d_material_flags", MTL_DIFFUSE_MIPMAP))
    
    bpy.types.Material.ls3d_flag_alpha_in_tex = BoolProperty(name="Alpha In Texture", description="Uses the Alpha channel in the Diffuse Texture file", get=make_getter("ls3d_material_flags", MTL_ALPHA_IN_TEX), set=make_setter("ls3d_material_flags", MTL_ALPHA_IN_TEX))
    bpy.types.Material.ls3d_flag_alpha_animated = BoolProperty(name="Anim Alpha", description="Enables Alpha Texture animation. Animated alpha textures end with 001 (first frame)", get=make_getter("ls3d_material_flags", MTL_ALPHA_ANIMATED), set=make_setter("ls3d_material_flags", MTL_ALPHA_ANIMATED))
    bpy.types.Material.ls3d_flag_diffuse_animated = BoolProperty(name="Anim Diffuse", description="Enables Diffuse Texture animation. Animated diffuse textures end with 01 (first frame)", get=make_getter("ls3d_material_flags", MTL_DIFFUSE_ANIMATED), set=make_setter("ls3d_material_flags", MTL_DIFFUSE_ANIMATED))
    bpy.types.Material.ls3d_flag_diffuse_colored = BoolProperty(name="Vertex Colors", description="Enables tinting of the texture using defined colors (Ambient, Diffuse, Emission)", get=make_getter("ls3d_material_flags", MTL_DIFFUSE_COLORED), set=make_setter("ls3d_material_flags", MTL_DIFFUSE_COLORED))
    bpy.types.Material.ls3d_flag_diffuse_doublesided = BoolProperty(name="Double Sided", description="Disables backface culling", get=make_getter("ls3d_material_flags", MTL_DIFFUSE_DOUBLESIDED), set=make_setter("ls3d_material_flags", MTL_DIFFUSE_DOUBLESIDED))
    bpy.types.Material.ls3d_flag_alpha_colorkey = BoolProperty(name="Color Key", description="Enables the use of Color Key from the Diffuse Texture (color key is the first color entry in the indexed color table)", get=make_getter("ls3d_material_flags", MTL_ALPHA_COLORKEY), set=make_setter("ls3d_material_flags", MTL_ALPHA_COLORKEY))
    bpy.types.Material.ls3d_flag_alphatex = BoolProperty(name="Use Alpha Texture", description="Enables the use of an Alpha Texture", get=make_getter("ls3d_material_flags", MTL_ALPHATEX), set=make_setter("ls3d_material_flags", MTL_ALPHATEX))
    bpy.types.Material.ls3d_flag_alpha_additive = BoolProperty(name="Mode Additive", description="Sets an Additive Mode for the Diffuse Texture (additive mode makes black color invisible, black color (RGB 0 0 0) acts as base of the additive mode)", get=make_getter("ls3d_material_flags", MTL_ALPHA_ADDITIVE), set=make_setter("ls3d_material_flags", MTL_ALPHA_ADDITIVE))

    # Standard Props
    bpy.types.Object.ls3d_lod_dist = FloatProperty(name="LOD Distance", default=0.0)
    bpy.types.Object.ls3d_user_props = StringProperty(name="User Props")
    bpy.types.Object.rot_mode = EnumProperty(items=(('1','All axes',''),('2','Single axis','')), name="Rot Mode")
    bpy.types.Object.rot_axis = EnumProperty(items=(('1','X',''),('2','Z',''),('3','Y','')), name="Rot Axis")
    bpy.types.Object.bbox_min = FloatVectorProperty(name="BBox Min")
    bpy.types.Object.bbox_max = FloatVectorProperty(name="BBox Max")
    
    # Sector Props
    # Internal Signed Storage with Limits
    bpy.types.Object.ls3d_sector_flags1 = IntProperty(default=0)
    bpy.types.Object.ls3d_sector_flags2 = IntProperty(default=0)
    
    # UI String Displays (Unsigned)
    bpy.types.Object.ls3d_sector_flags1_str = StringProperty(name="Raw Flags 1", description="Raw Unsigned Integer", get=get_sector_flags1_unsigned, set=set_sector_flags1_unsigned)
    bpy.types.Object.ls3d_sector_flags2_str = StringProperty(name="Raw Flags 2", description="Raw Unsigned Integer", get=get_sector_flags2_unsigned, set=set_sector_flags2_unsigned)

    # Boolean accessors for Sector Flags 1
    bpy.types.Object.sf_enabled = BoolProperty(name="Enabled", description="Enables the Sector", get=make_getter("ls3d_sector_flags1", SF_ENABLED), set=make_setter("ls3d_sector_flags1", SF_ENABLED))
    bpy.types.Object.sf_unknown7 = BoolProperty(name="Unknown 7", description="", get=make_getter("ls3d_sector_flags1", SF_UNKNOWN7), set=make_setter("ls3d_sector_flags1", SF_UNKNOWN7))
    bpy.types.Object.sf_unknown8 = BoolProperty(name="Unknown 8", description="Sets the Sector to act as an interior?", get=make_getter("ls3d_sector_flags1", SF_UNKNOWN8), set=make_setter("ls3d_sector_flags1", SF_UNKNOWN8))
    
    # Portal Props
    bpy.types.Object.ls3d_portal_flags = IntProperty()
    bpy.types.Object.ls3d_portal_near = FloatProperty()
    bpy.types.Object.ls3d_portal_far = FloatProperty()
    
    # Portal Plane Data (Reference Only)
    bpy.types.Object.ls3d_portal_normal = FloatVectorProperty(name="Plane Normal",description="Imported Plane Normal. NOTE: This is recalculated from geometry upon Export.",subtype='XYZ',size=3,precision=8)
    bpy.types.Object.ls3d_portal_dot = FloatProperty(name="Plane Distance",description="Imported Plane Distance (Dot Product). NOTE: This is recalculated from geometry upon Export.",precision=8)

    bpy.types.Object.pf_enabled = BoolProperty(name="Enabled", description="Enables rendering of the portal", get=make_getter("ls3d_portal_flags", PF_ENABLED), set=make_setter("ls3d_portal_flags", PF_ENABLED))
    bpy.types.Object.pf_unknown4 = BoolProperty(name="Unknown 4", description="? Portal is a Mirror surface ?", get=make_getter("ls3d_portal_flags", PF_UNKNOWN4), set=make_setter("ls3d_portal_flags", PF_UNKNOWN4))
    bpy.types.Object.pf_unknown1 = BoolProperty(name="Unknown 1", description="", get=make_getter("ls3d_portal_flags", PF_UNKNOWN1), set=make_setter("ls3d_portal_flags", PF_UNKNOWN1))
    bpy.types.Object.pf_unknown2 = BoolProperty(name="Unknown 2", description="", get=make_getter("ls3d_portal_flags", PF_UNKNOWN2), set=make_setter("ls3d_portal_flags", PF_UNKNOWN2))

    # Mirror Props
    bpy.types.Object.ls3d_mirror_color = bpy.props.FloatVectorProperty(name="Mirror Color", description="This color is visible when the Mirror Reflection is out of range or as a sky color (skybox isn't usually visible in mirror)", subtype='COLOR', size=3, min=0.0, max=1.0, default=(1.0, 1.0, 1.0))
    bpy.types.Object.ls3d_mirror_range = bpy.props.FloatProperty(name="Mirror Refelction Range", min=0.0, default=0.0)

    # Lensflare Props
    bpy.types.Object.ls3d_glow_position = bpy.props.FloatProperty(name="Position", description="Screen offset (Mafia lens flare)", default=0.0)
    bpy.types.Object.ls3d_glow_material = bpy.props.PointerProperty(name="Material", description="Lens flare material", type=bpy.types.Material)

    # Target props
    bpy.types.Object.ls3d_target_flags = bpy.props.IntProperty(name="Flags", description="Target frame flags (u16)", default=1, min=0, max=65535)
    bpy.types.Object.ls3d_target_objects = bpy.props.CollectionProperty(name="Target Objects", type=LS3DTargetObject)
    bpy.types.Object.ls3d_target_objects_index = bpy.props.IntProperty(name="Active Index", default=0)
    bpy.types.Object.ls3d_target_add_name = bpy.props.StringProperty(name="Add Target", description="Object name, or 'armature:bone' for a bone", default="")

    bpy.types.Material.ls3d_color_key = bpy.props.FloatVectorProperty(name="Color Key", size=3, default=(0.0, 0.0, 0.0))

    # Pose Bone Props
    bpy.types.PoseBone.cull_flags     = IntProperty(name="Culling Flags", default=0, min=0)
    bpy.types.PoseBone.user_props     = StringProperty(name="User Props", default="")
    bpy.types.PoseBone.cf_enabled     = BoolProperty(name="Enabled",     get=make_getter("cull_flags", CF_ENABLED),     set=make_setter("cull_flags", CF_ENABLED))
    bpy.types.PoseBone.cf_unknown2    = BoolProperty(name="Unknown 2",   get=make_getter("cull_flags", CF_UNKNOWN2),    set=make_setter("cull_flags", CF_UNKNOWN2))
    bpy.types.PoseBone.cf_unknown3    = BoolProperty(name="Unknown 3",   get=make_getter("cull_flags", CF_UNKNOWN3),    set=make_setter("cull_flags", CF_UNKNOWN3))
    bpy.types.PoseBone.cf_cast_shadow = BoolProperty(name="Cast Shadow", get=make_getter("cull_flags", CF_CAST_SHADOW), set=make_setter("cull_flags", CF_CAST_SHADOW))
    bpy.types.PoseBone.cf_unknown5    = BoolProperty(name="Unknown 5",   get=make_getter("cull_flags", CF_UNKNOWN5),    set=make_setter("cull_flags", CF_UNKNOWN5))
    bpy.types.PoseBone.cf_unknown6    = BoolProperty(name="Unknown 6",   get=make_getter("cull_flags", CF_UNKNOWN6),    set=make_setter("cull_flags", CF_UNKNOWN6))
    bpy.types.PoseBone.cf_hierarchy   = BoolProperty(name="Hierarchy ?", get=make_getter("cull_flags", CF_HIERARCHY),   set=make_setter("cull_flags", CF_HIERARCHY))
    bpy.types.PoseBone.cf_unknown8    = BoolProperty(name="Unknown 8",   get=make_getter("cull_flags", CF_UNKNOWN8),    set=make_setter("cull_flags", CF_UNKNOWN8))

    bpy.utils.register_class(LS3DMorphTarget)
    bpy.utils.register_class(LS3DMorphGroup)
    bpy.utils.register_class(LS3D_UL_MorphGroups)
    bpy.utils.register_class(LS3D_UL_MorphTargets)
    bpy.utils.register_class(LS3D_OT_MorphSelectToggle)
    bpy.utils.register_class(LS3D_OT_MorphGroup)
    bpy.utils.register_class(LS3D_OT_MorphTarget)
    bpy.utils.register_class(LS3D_OT_MorphMakeBasis)
    bpy.utils.register_class(LS3D_OT_MorphTransfer)
    bpy.utils.register_class(The4DSPanelMorph)
    bpy.utils.register_class(LS3D_OT_MorphAddExisting)
    bpy.utils.register_class(LS3D_OT_MorphAddExistingPick)
    bpy.types.Object.ls3d_morph_groups       = CollectionProperty(type=LS3DMorphGroup)
    bpy.app.handlers.depsgraph_update_post.append(ls3d_joint_scale_init)
    bpy.types.Object.ls3d_active_morph_group = IntProperty(default=0)

    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
        bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    except: pass
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    
def unregister():
    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
        bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    except: pass

    # --- Handler ---
    if ls3d_joint_scale_init in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(ls3d_joint_scale_init)

    # --- Morph classes (delete collection props BEFORE their PropertyGroup classes) ---
    del bpy.types.Object.ls3d_active_morph_group
    del bpy.types.Object.ls3d_morph_groups
    bpy.utils.unregister_class(The4DSPanelMorph)
    bpy.utils.unregister_class(LS3D_OT_MorphAddExisting)
    bpy.utils.unregister_class(LS3D_OT_MorphAddExistingPick)
    bpy.utils.unregister_class(LS3D_OT_MorphMakeBasis)
    bpy.utils.unregister_class(LS3D_OT_MorphTransfer)
    bpy.utils.unregister_class(LS3D_OT_MorphTarget)
    bpy.utils.unregister_class(LS3D_OT_MorphGroup)
    bpy.utils.unregister_class(LS3D_OT_MorphSelectToggle)
    bpy.utils.unregister_class(LS3D_UL_MorphTargets)
    bpy.utils.unregister_class(LS3D_UL_MorphGroups)
    bpy.utils.unregister_class(LS3DMorphGroup)
    bpy.utils.unregister_class(LS3DMorphTarget)

    # --- Target classes (delete collection props BEFORE their PropertyGroup class) ---
    del bpy.types.Object.ls3d_target_objects
    del bpy.types.Object.ls3d_target_objects_index
    del bpy.types.Object.ls3d_target_add_name
    del bpy.types.Object.ls3d_target_flags
    bpy.utils.unregister_class(LS3D_OT_RemoveTargetObject)
    bpy.utils.unregister_class(LS3D_OT_AddTargetObject)
    bpy.utils.unregister_class(LS3DTargetObject)

    # --- Operator / Panel / Preferences classes ---
    bpy.utils.unregister_class(LS3D_OT_CreateMaterial)
    bpy.utils.unregister_class(LS3D_OT_SetBlendBone)
    bpy.utils.unregister_class(LS3D_OT_ResultPopup)
    bpy.utils.unregister_class(The4DSPanelMaterial)
    bpy.utils.unregister_class(The4DSPanel)
    bpy.utils.unregister_class(Import4DS)
    bpy.utils.unregister_class(Export4DS)
    bpy.utils.unregister_class(LS3D_AddonPreferences)

    # --- MODEL ---
    del bpy.types.Scene.ls3d_animated_object_count

    # --- OBJECT PROPERTIES ---
    del bpy.types.Object.ls3d_frame_type_override
    del bpy.types.Object.ls3d_frame_type
    del bpy.types.Object.visual_type

    # --- OBJECT CULLING FLAGS ---
    del bpy.types.Object.cull_flags
    del bpy.types.Object.cf_enabled
    del bpy.types.Object.cf_unknown2
    del bpy.types.Object.cf_unknown3
    del bpy.types.Object.cf_cast_shadow
    del bpy.types.Object.cf_unknown5
    del bpy.types.Object.cf_unknown6
    del bpy.types.Object.cf_hierarchy
    del bpy.types.Object.cf_unknown8

    # --- VISUAL RENDER FLAGS ---
    del bpy.types.Object.render_flags
    del bpy.types.Object.render_flags2
    del bpy.types.Object.rf1_unknown1
    del bpy.types.Object.rf1_unknown2
    del bpy.types.Object.rf1_unknown3
    del bpy.types.Object.rf1_unknown4
    del bpy.types.Object.rf1_unknown5
    del bpy.types.Object.rf1_unknown6
    del bpy.types.Object.rf1_hidemesh
    del bpy.types.Object.rf1_noshading
    del bpy.types.Object.rf2_zbias
    del bpy.types.Object.rf2_recieve_dynamic_shadow_diffuse
    del bpy.types.Object.rf2_recieve_dynamic_shadow_alpha
    del bpy.types.Object.rf2_mirrorable
    del bpy.types.Object.rf2_unknown5
    del bpy.types.Object.rf2_recieve_projection_diffuse
    del bpy.types.Object.rf2_recieve_projection_alpha
    del bpy.types.Object.rf2_no_fog

    # --- MATERIAL PROPERTIES ---
    del bpy.types.Material.ls3d_ambient_color
    del bpy.types.Material.ls3d_diffuse_color
    del bpy.types.Material.ls3d_emission_color
    del bpy.types.Material.ls3d_diffuse_tex
    del bpy.types.Material.ls3d_alpha_tex
    del bpy.types.Material.ls3d_env_tex
    del bpy.types.Material.ls3d_env_amount
    del bpy.types.Material.ls3d_opacity
    del bpy.types.Material.ls3d_anim_frames
    del bpy.types.Material.ls3d_anim_period

    # --- MATERIAL FLAGS ---
    del bpy.types.Material.ls3d_material_flags
    del bpy.types.Material.ls3d_material_flags_str
    del bpy.types.Material.ls3d_flag_misc_unlit
    del bpy.types.Material.ls3d_flag_env_overlay
    del bpy.types.Material.ls3d_flag_env_multiply
    del bpy.types.Material.ls3d_flag_env_additive
    del bpy.types.Material.ls3d_flag_env_projy
    del bpy.types.Material.ls3d_flag_env_detaily
    del bpy.types.Material.ls3d_flag_env_detailz
    del bpy.types.Material.ls3d_flag_alpha_enable
    del bpy.types.Material.ls3d_flag_disable_u_tiling
    del bpy.types.Material.ls3d_flag_disable_v_tiling
    del bpy.types.Material.ls3d_flag_diffuse_enable
    del bpy.types.Material.ls3d_flag_env_enable
    del bpy.types.Material.ls3d_flag_diffuse_mipmap
    del bpy.types.Material.ls3d_flag_alpha_in_tex
    del bpy.types.Material.ls3d_flag_alpha_animated
    del bpy.types.Material.ls3d_flag_diffuse_animated
    del bpy.types.Material.ls3d_flag_diffuse_colored
    del bpy.types.Material.ls3d_flag_diffuse_doublesided
    del bpy.types.Material.ls3d_flag_alpha_colorkey
    del bpy.types.Material.ls3d_flag_alphatex
    del bpy.types.Material.ls3d_flag_alpha_additive
    del bpy.types.Material.ls3d_color_key

    # --- Standard Object Props ---
    del bpy.types.Object.ls3d_lod_dist
    del bpy.types.Object.ls3d_user_props
    del bpy.types.Object.rot_mode
    del bpy.types.Object.rot_axis
    del bpy.types.Object.bbox_min
    del bpy.types.Object.bbox_max

    # --- Sector Props ---
    del bpy.types.Object.ls3d_sector_flags1
    del bpy.types.Object.ls3d_sector_flags2
    del bpy.types.Object.ls3d_sector_flags1_str
    del bpy.types.Object.ls3d_sector_flags2_str
    del bpy.types.Object.sf_enabled
    del bpy.types.Object.sf_unknown7
    del bpy.types.Object.sf_unknown8

    # --- Portal Props ---
    del bpy.types.Object.ls3d_portal_flags
    del bpy.types.Object.ls3d_portal_near
    del bpy.types.Object.ls3d_portal_far
    del bpy.types.Object.ls3d_portal_normal
    del bpy.types.Object.ls3d_portal_dot
    del bpy.types.Object.pf_enabled
    del bpy.types.Object.pf_unknown4
    del bpy.types.Object.pf_unknown1
    del bpy.types.Object.pf_unknown2

    # --- Mirror Props ---
    del bpy.types.Object.ls3d_mirror_color
    del bpy.types.Object.ls3d_mirror_range

    # --- Lensflare Props ---
    del bpy.types.Object.ls3d_glow_position
    del bpy.types.Object.ls3d_glow_material

    # --- Pose Bone Props ---
    del bpy.types.PoseBone.cull_flags
    del bpy.types.PoseBone.user_props
    del bpy.types.PoseBone.cf_enabled
    del bpy.types.PoseBone.cf_unknown2
    del bpy.types.PoseBone.cf_unknown3
    del bpy.types.PoseBone.cf_cast_shadow
    del bpy.types.PoseBone.cf_unknown5
    del bpy.types.PoseBone.cf_unknown6
    del bpy.types.PoseBone.cf_hierarchy
    del bpy.types.PoseBone.cf_unknown8

if __name__ == "__main__":
    register()