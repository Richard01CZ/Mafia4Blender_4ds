from datetime import datetime
import os
import bpy # type: ignore
import bmesh # type: ignore
import struct
import re
import math
from mathutils import Quaternion, Matrix, Vector # type: ignore
from bpy_extras.io_utils import ImportHelper, ExportHelper # type: ignore
from bpy.props import StringProperty, EnumProperty, IntProperty, FloatProperty, FloatVectorProperty, BoolProperty # type: ignore
from bpy.types import AddonPreferences # type: ignore
bl_info = {
    "name": "LS3D 4DS Importer/Exporter",
    "author": "Sev3n, Richard01_CZ, Grok 4 AI, Google Gemini 3 Pro Preview, ChatGPT 5.2",
    "version": (0, 0, 1, 'preview' ),
    "blender": (5, 0, 1),
    "location": "File > Import/Export > 4DS Model File",
    "description": "Import and export LS3D .4ds files (Mafia)",
    "category": "Import-Export",
}
# FileVersion consts
VERSION_MAFIA = 29
VERSION_HD2 = 41
VERSION_CHAMELEON = 42

# Frame Types
FRAME_VISUAL = 1        # 3D Object                 COMPLETE ?
FRAME_LIGHT = 2         # UNUSPPORTED
FRAME_CAMERA = 3
FRAME_SOUND = 4
FRAME_SECTOR = 5        # 3D Object Wireframe       
FRAME_DUMMY = 6         # Empty (Cube)
FRAME_TARGET = 7        # Empty (Plain Axis)
FRAME_USER = 8          # HD2
FRAME_MODEL = 9         # Empty (Arrows)            TO DO
FRAME_JOINT = 10        # Armature/Bones            TO DO
FRAME_VOLUME = 11       # HD2
FRAME_OCCLUDER = 12     # 3D Object Wireframe       
FRAME_SCENE = 13        # HD2
FRAME_AREA = 14         # HD2
FRAME_LANDSCAPE = 15    # HD2

# Visual Types
VISUAL_OBJECT = 0           # COMPLETE ?
VISUAL_LITOBJECT = 1        # TO DO
VISUAL_SINGLEMESH = 2       # TO DO
VISUAL_SINGLEMORPH = 3      # TO DO
VISUAL_BILLBOARD = 4        # COMPLETE
VISUAL_MORPH = 5            # TO DO
VISUAL_LENS = 6             # TO DO
VISUAL_PROJECTOR = 7        # UNSUPPORTED
VISUAL_MIRROR = 8           # TO DO
VISUAL_EMITOR = 9           # UNSUPPORTED

# Material Flags (Full 32-bit map)
MTL_MISC_UNLIT              = 0x00000001
MTL_ENV_OVERLAY             = 0x00000100
MTL_ENV_MULTIPLY            = 0x00000200
MTL_ENV_ADDITIVE            = 0x00000400
MTL_ENVTEX                  = 0x00000800
MTL_ALPHA_ENABLE            = 0x00008000
MTL_DISABLE_U_TILING        = 0x00010000
MTL_DISABLE_V_TILING        = 0x00020000
MTL_DIFFUSE_ENABLE          = 0x00040000
MTL_ENV_ENABLE              = 0x00080000
MTL_ENV_PROJY               = 0x00001000
MTL_ENV_DETAILY             = 0x00002000
MTL_ENV_DETAILZ             = 0x00004000
MTL_UNKNOWN_20              = 0x00100000
MTL_UNKNOWN_21              = 0x00200000
MTL_UNKNOWN_22              = 0x00400000
MTL_DIFFUSE_MIPMAP          = 0x00800000
MTL_ALPHA_IN_TEX            = 0x01000000
MTL_ALPHA_ANIMATED          = 0x02000000
MTL_DIFFUSE_ANIMATED        = 0x04000000
MTL_DIFFUSE_COLORED         = 0x08000000
MTL_DIFFUSE_DOUBLESIDED     = 0x10000000
MTL_ALPHA_COLORKEY          = 0x20000000
MTL_ALPHATEX                = 0x40000000
MTL_ALPHA_ADDITIVE          = 0x80000000

# --- VISUAL RENDER FLAGS (Byte 1) ---
RF_CAST_SHADOW      = 1 << 0  # 1   - Object casts a dynamic shadow.
RF_RECEIVE_SHADOW   = 1 << 1  # 2   - Object receives shadows cast by other objects.
RF_DRAW_LAST        = 1 << 2  # 4   - Rendered after opaque geometry (Required for alpha blending/transparency).
RF_ZBIAS            = 1 << 3  # 8   - Applies a small depth offset to prevent Z-fighting (flickering) on decals.
RF_BRIGHT           = 1 << 4  # 16  - Unlit/Fullbright. Ignores scene lighting (always fully illuminated).
RF_WIRE_BOUND       = 1 << 5  # 32  - Hidden/Collision Only. Object is invisible in-game but physically active.
RF_UNUSED_6         = 1 << 6  # 64  - Unknown/Unused.
RF_UNUSED_7         = 1 << 7  # 128 - Unknown/Unused.

# --- VISUAL LOGIC FLAGS (Byte 2) ---
LF_DECAL            = 1 << 0  # 1   - Treats mesh as a surface decal optimization.
LF_STENCIL          = 1 << 1  # 2   - Enables stencil buffer operations (used for stencil shadow volumes).
LF_MIRROR           = 1 << 2  # 4   - Surface acts as a real-time planar mirror (Performance heavy).
LF_FADE_OUT         = 1 << 3  # 8   - Object fades out transparently at max distance instead of popping out.
LF_2D               = 1 << 4  # 16  - Renders as 2D overlay. Disables Z-buffer depth check (draws on top).
LF_PROJECTOR        = 1 << 5  # 32  - Mesh behaves as a texture projector (e.g., car headlights).
LF_SOUND_OCCLUDER   = 1 << 6  # 64  - Geometry acts as a physical barrier for sound, muffling audio behind it.
LF_NO_FOG           = 1 << 7  # 128 - Object is unaffected by scene fog (used for Skyboxes/Horizons).

class LS3D_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    textures_path: StringProperty(name="Path to Textures", description='Path to the textures "maps" folder. This path is used by the importer.', subtype='DIR_PATH', default=r"D:/Hry/Mafia Editovani/maps") # type: ignore / drž píču už, funguješ

    def draw(self, context):
        layout = self.layout
        layout.label(text="LS3D Configuration", icon='SETTINGS')
        layout.prop(self, "textures_path")


class The4DSPanel(bpy.types.Panel):
    bl_label = "4DS Object Properties"
    bl_idname = "OBJECT_PT_4ds"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"
    
    def draw(self, context):
        obj = context.object
        layout = self.layout
        
        # Global Scene Settings
        box = layout.box()
        box.label(text="Scene Settings", icon='SCENE_DATA')
        box.prop(context.scene, "ls3d_is_animated")
        
        if not obj: return
        
        layout.separator()
        layout.prop(obj, "ls3d_frame_type", text="Frame Type")
        current_type = obj.ls3d_frame_type
        
        # --- DETECT IF PORTAL ---
        # Strictly checks: 
        # 1. Object is Type 5 (Sector)
        # 2. Parent exists and is Type 5 (Sector)
        # 3. Name ends with _portal<number>
        is_portal = False
        
        if current_type == '5': # Rule 1: Object must be a Sector Frame
            if obj.parent:
                parent_type = getattr(obj.parent, "ls3d_frame_type", '1')
                if parent_type == '5': # Rule 2: Parent must be a Sector
                    # Rule 3: Check suffix (e.g., Room_portal1)
                    if re.search(r"_portal\d+$", obj.name, re.IGNORECASE):
                        is_portal = True

        # =========================================================
        # DRAW LOGIC
        # =========================================================

        # --- CASE A: PORTAL (Strict Logic) ---
        if is_portal:
            box = layout.box()
            box.label(text="Portal Config", icon='OUTLINER_OB_LIGHT')
            
            # Raw Int
            box.prop(obj, "ls3d_portal_flags", text="Raw Flags (Int)")
            
            # Values
            row = box.row(align=True)
            row.prop(obj, "ls3d_portal_near", text="Near")
            row.prop(obj, "ls3d_portal_far", text="Far")
            
            # Flags
            box.label(text="Flags:")
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "pf_bit0", text="(Active)") 
            grid.prop(obj, "pf_bit1", text="Bit 1")
            grid.prop(obj, "pf_enabled", text="Bit 2 (Possible Active flag)") 
            grid.prop(obj, "pf_mirror", text="Bit 3 (Mirror)")
            
            # Portals also need Node Culling flags
            box = layout.box()
            box.label(text="Node Culling Flags", icon='PROPERTIES')
            row = box.row()
            row.prop(obj, "cull_flags", text="Raw Int (Culling)")
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "cf_node_visible")
            grid.prop(obj, "cf_node_cam_coll")
            grid.prop(obj, "cf_node_collision")
            grid.prop(obj, "cf_node_castshadow")
            grid.prop(obj, "cf_node_update")
            grid.prop(obj, "cf_node_freeze")
            grid.prop(obj, "cf_node_hierarchy")
            
            box = layout.box()
            box.prop(obj, "ls3d_user_props", text="User Props", icon='TEXT')

        # --- CASE B: STANDARD VISUAL MESH ---
        elif current_type == '1' and obj.type == 'MESH':
            layout.prop(obj, "visual_type", text="Mesh Type")
            
            # Render Flags
            box = layout.box()
            box.label(text="Render Flags", icon='RESTRICT_RENDER_OFF')
            row = box.row()
            row.prop(obj, "render_flags", text="Raw Int 1 (Byte 1)")
            
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "rf1_cast_shadow")
            grid.prop(obj, "rf1_receive_shadow")
            grid.prop(obj, "rf1_draw_last")
            grid.prop(obj, "rf1_zbias")
            grid.prop(obj, "rf1_bright")
            
            # Logic Flags
            box = layout.box()
            box.label(text="Logic Flags", icon='MODIFIER')
            row = box.row()
            row.prop(obj, "render_flags2", text="Raw Int 2 (Byte 2)")
            
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "rf2_decal")
            grid.prop(obj, "rf2_stencil")
            grid.prop(obj, "rf2_mirror")
            grid.prop(obj, "rf2_fadeout")
            grid.prop(obj, "rf2_proj")
            grid.prop(obj, "rf2_nofog")
            
            # Billboard / Mirror Props
            if hasattr(obj, "visual_type"):
                if obj.visual_type == '4': # Billboard
                    box = layout.box()
                    box.label(text="Billboard", icon='IMAGE_PLANE')
                    box.prop(obj, "rot_mode")
                    if obj.rot_mode == '2': box.prop(obj, "rot_axis")
                elif obj.visual_type == '8': # Mirror
                    box = layout.box()
                    box.label(text="Mirror", icon='MOD_MIRROR')
                    box.prop(obj, "mirror_color")
                    box.prop(obj, "mirror_dist")
            
            # Node Properties
            box = layout.box()
            box.label(text="Node Culling Flags", icon='PROPERTIES')
            row = box.row()
            row.prop(obj, "cull_flags", text="Raw Int (Culling)")
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "cf_node_visible")
            grid.prop(obj, "cf_node_cam_coll")
            grid.prop(obj, "cf_node_collision")
            grid.prop(obj, "cf_node_castshadow")
            grid.prop(obj, "cf_node_update")
            grid.prop(obj, "cf_node_freeze")
            grid.prop(obj, "cf_node_hierarchy")
            
            box = layout.box()
            box.prop(obj, "ls3d_user_props", text="User Props", icon='TEXT')

            # LOD SETTINGS (Bottom)
            box = layout.box()
            box.label(text="Level-Of-Detail Settings", icon='MESH_DATA')
            box.prop(obj, "ls3d_lod_dist", text="Fade-In Distance")

       # --- CASE C: SECTOR (Not a Portal) ---
        elif current_type == '5':
            box = layout.box()
            box.label(text="Sector Flags", icon='SCENE_DATA')
            
            # Flags 1 (Using String Property for Unsigned Display)
            row = box.row()
            row.prop(obj, "ls3d_sector_flags1_str", text="Raw Int 1")
            
            # Flags 2 (Using String Property for Unsigned Display)
            row = box.row()
            row.prop(obj, "ls3d_sector_flags2_str", text="Raw Int 2")
            
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "sf_active")
            grid.prop(obj, "sf_collision")
            grid.prop(obj, "sf_indoor")
            
            # Node Properties
            box = layout.box()
            box.label(text="Node Culling Flags", icon='PROPERTIES')
            row = box.row()
            row.prop(obj, "cull_flags", text="Raw Int (Culling)")
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "cf_node_visible")
            grid.prop(obj, "cf_node_cam_coll")
            grid.prop(obj, "cf_node_collision")
            grid.prop(obj, "cf_node_castshadow")
            grid.prop(obj, "cf_node_update")
            grid.prop(obj, "cf_node_freeze")
            grid.prop(obj, "cf_node_hierarchy")
            
            box = layout.box()
            box.prop(obj, "ls3d_user_props", text="User Props", icon='TEXT')

        # --- CASE D: DUMMY / TARGET / MODEL ---
        elif current_type in ('6', '7', '9'):
            if current_type == '6':
                box = layout.box()
                box.label(text="Dummy Bounding Box (Local)", icon='SHADING_BBOX')
                if "bbox_min" in obj and "bbox_max" in obj:
                    col = box.column(align=True)
                    col.prop(obj, '["bbox_min"]', text="Min (XYZ)")
                    col.prop(obj, '["bbox_max"]', text="Max (XYZ)")
                else:
                    box.label(text="No BBox Data (Will auto-generate)", icon='ERROR')
            
            # Node Properties
            box = layout.box()
            box.label(text="Node Culling Flags", icon='PROPERTIES')
            row = box.row()
            row.prop(obj, "cull_flags", text="Raw Int (Culling)")
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "cf_node_visible")
            grid.prop(obj, "cf_node_cam_coll")
            grid.prop(obj, "cf_node_collision")
            grid.prop(obj, "cf_node_castshadow")
            grid.prop(obj, "cf_node_update")
            grid.prop(obj, "cf_node_freeze")
            grid.prop(obj, "cf_node_hierarchy")
            
            box = layout.box()
            box.prop(obj, "ls3d_user_props", text="User Props", icon='TEXT')
            
        # --- CASE E: DEFAULT FALLBACK ---
        else:
            box = layout.box()
            box.label(text="Node Culling Flags", icon='PROPERTIES')
            row = box.row()
            row.prop(obj, "cull_flags", text="Raw Int (Culling)")
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(obj, "cf_node_visible")
            grid.prop(obj, "cf_node_cam_coll")
            grid.prop(obj, "cf_node_collision")
            grid.prop(obj, "cf_node_castshadow")
            grid.prop(obj, "cf_node_update")
            grid.prop(obj, "cf_node_freeze")
            grid.prop(obj, "cf_node_hierarchy")
            
            box = layout.box()
            box.prop(obj, "ls3d_user_props", text="User Props", icon='TEXT')

class The4DSPanelMaterial(bpy.types.Panel):
    bl_label = "4DS Material Properties"
    bl_idname = "MATERIAL_PT_4ds"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    
    def draw(self, context):
        mat = context.material
        if not mat: return
        layout = self.layout
        
        # --- Colors ---
        box = layout.box()
        box.label(text="Colors", icon='COLOR')
        col = box.column(align=True)
        col.prop(mat, "ls3d_diffuse_color", text="Diffuse")
        col.prop(mat, "ls3d_ambient_color", text="Ambient")
        col.prop(mat, "ls3d_emission_color", text="Emission")
        
        # --- RAW FLAGS INT (Using String for Positive Display) ---
        box = layout.box()
        box.label(text="Global Material Flags", icon='PREFERENCES')
        box.prop(mat, "ls3d_material_flags_str", text="Raw Int (Unsigned)")

        # --- Diffuse Settings ---
        layout.label(text="Diffuse & General", icon='TEXTURE')
        box = layout.box()
        col = box.column(align=True)
        
        row = col.row()
        row.prop(mat, "ls3d_flag_misc_unlit") 
        row.prop(mat, "ls3d_flag_diffuse_enable")
        
        row = col.row()
        row.prop(mat, "ls3d_flag_diffuse_doublesided")
        row.prop(mat, "ls3d_flag_diffuse_colored")
        
        row = col.row()
        row.prop(mat, "ls3d_flag_diffuse_mipmap")
        row.prop(mat, "ls3d_flag_diffuse_animated")
        
        row = col.row()
        row.prop(mat, "ls3d_flag_disable_u_tiling")
        row.prop(mat, "ls3d_flag_disable_v_tiling")
        
        # DIFFUSE ANIMATION
        if mat.ls3d_flag_diffuse_animated:
            subbox = box.box()
            subbox.label(text="Diffuse Animation", icon='ANIM')
            col_anim = subbox.column(align=True)
            col_anim.prop(mat, "ls3d_diffuse_anim_frames")
            col_anim.prop(mat, "ls3d_diffuse_anim_period")

        # --- Alpha Settings ---
        layout.label(text="Alpha / Transparency", icon='TRIA_RIGHT')
        box = layout.box()
        col = box.column(align=True)
        row = col.row()
        row.prop(mat, "ls3d_flag_alpha_enable")
        row.prop(mat, "ls3d_flag_alphatex")
        row = col.row()
        row.prop(mat, "ls3d_flag_alpha_colorkey")
        row.prop(mat, "ls3d_flag_alpha_additive")
        row = col.row()
        row.prop(mat, "ls3d_flag_alpha_in_tex")
        row.prop(mat, "ls3d_flag_alpha_animated")
        
        # ALPHA ANIMATION
        if mat.ls3d_flag_alpha_animated:
            subbox = box.box()
            subbox.label(text="Alpha Animation", icon='ANIM')
            col_anim = subbox.column(align=True)
            col_anim.prop(mat, "ls3d_alpha_anim_frames")
            col_anim.prop(mat, "ls3d_alpha_anim_period")

        # --- Environment Settings ---
        layout.label(text="Environment Mapping", icon='WORLD_DATA')
        box = layout.box()
        col = box.column(align=True)
        row = col.row()
        row.prop(mat, "ls3d_flag_env_enable")
        row.prop(mat, "ls3d_flag_env_use_map")
        row = col.row()
        row.prop(mat, "ls3d_flag_env_overlay")
        row.prop(mat, "ls3d_flag_env_multiply")
        row.prop(mat, "ls3d_flag_env_additive")
        row = col.row()
        row.prop(mat, "ls3d_flag_env_projy")
        row.prop(mat, "ls3d_flag_env_detaily")
        row.prop(mat, "ls3d_flag_env_detailz")

        layout.separator()
        layout.operator("node.add_ls3d_env_setup", icon='NODETREE', text="Add Env Setup")
        layout.operator("node.add_ls3d_group", icon='NODETREE', text="Add Material Node")

def safe_link(tree, from_socket, to_socket):
    if from_socket and to_socket:
        tree.links.new(from_socket, to_socket)

def get_or_create_env_group():
    group_name = "LS3D Environment"
    
    if group_name in bpy.data.node_groups:
        return bpy.data.node_groups[group_name]
    
    ng = bpy.data.node_groups.new(name=group_name, type='ShaderNodeTree')
    
    # Interface
    if not ng.interface.items_tree:
        ng.interface.new_socket("Color", in_out='INPUT', socket_type='NodeSocketColor')
        ng.interface.new_socket("Intensity", in_out='INPUT', socket_type='NodeSocketFloat')
        ng.interface.new_socket("Output", in_out='OUTPUT', socket_type='NodeSocketColor')
        
        if "Intensity" in ng.interface.items_tree:
            ng.interface.items_tree["Intensity"].default_value = 1.0
            ng.interface.items_tree["Intensity"].min_value = 0.0
            ng.interface.items_tree["Intensity"].max_value = 100.0
    
    if not ng.nodes:
        input_node = ng.nodes.new('NodeGroupInput')
        input_node.location = (-300, 0)
        output_node = ng.nodes.new('NodeGroupOutput')
        output_node.location = (300, 0)
        
        # Multiply Color * Intensity
        mix = ng.nodes.new('ShaderNodeMixRGB')
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Fac'].default_value = 1.0
        mix.location = (0, 0)
        
        ng.links.new(input_node.outputs.get("Color"), mix.inputs[1])
        ng.links.new(input_node.outputs.get("Intensity"), mix.inputs[2])
        ng.links.new(mix.outputs[0], output_node.inputs.get("Output"))
    
    return ng

def get_or_create_ls3d_group():
    group_name = "LS3D Material Data"
    
    if group_name in bpy.data.node_groups:
        ng = bpy.data.node_groups[group_name]
    else:
        ng = bpy.data.node_groups.new(name=group_name, type='ShaderNodeTree')

    # Interface (Emission Removed)
    if not ng.interface.items_tree:
        ng.interface.new_socket("Diffuse Map", in_out='INPUT', socket_type='NodeSocketColor')
        ng.interface.new_socket("Alpha Map", in_out='INPUT', socket_type='NodeSocketColor')
        ng.interface.new_socket("Environment Map", in_out='INPUT', socket_type='NodeSocketColor')
        ng.interface.new_socket("Opacity", in_out='INPUT', socket_type='NodeSocketFloat')
        ng.interface.new_socket("Anim Frames", in_out='INPUT', socket_type='NodeSocketFloat')
        ng.interface.new_socket("Anim Period", in_out='INPUT', socket_type='NodeSocketFloat')
        # Emission socket removed as requested
        ng.interface.new_socket("BSDF", in_out='OUTPUT', socket_type='NodeSocketShader')

    # Defaults
    for socket in ng.interface.items_tree:
        if socket.bl_socket_idname == 'NodeSocketColor':
            socket.default_value = (1.0, 1.0, 1.0, 1.0)
            if "Environment Map" in socket.name: socket.default_value = (0.0, 0.0, 0.0, 1.0)
        elif socket.bl_socket_idname == 'NodeSocketFloat':
            if "Opacity" in socket.name: socket.default_value = 100.0

    if not ng.nodes:
        input_node = ng.nodes.new('NodeGroupInput')
        input_node.location = (-1000, 0)
        output_node = ng.nodes.new('NodeGroupOutput')
        output_node.location = (600, 0)
        
        # Add Diffuse + Environment
        add_env = ng.nodes.new('ShaderNodeMixRGB')
        add_env.blend_type = 'ADD'
        add_env.inputs['Fac'].default_value = 1.0
        add_env.location = (-700, 200)

        # Opacity Scaling
        math_op_scale = ng.nodes.new('ShaderNodeMath')
        math_op_scale.operation = 'DIVIDE'
        math_op_scale.inputs[1].default_value = 100.0
        math_op_scale.location = (-900, -100)

        # Alpha Calc
        math_alpha = ng.nodes.new('ShaderNodeMath')
        math_alpha.operation = 'MULTIPLY'
        math_alpha.location = (-700, -100)

        # Principled BSDF
        principled = ng.nodes.new('ShaderNodeBsdfPrincipled')
        principled.location = (0, 200)
        principled.inputs["Roughness"].default_value = 1.0 
        principled.inputs["Specular IOR Level"].default_value = 0.0
        principled.inputs["Metallic"].default_value = 0.0
        
        # Links
        safe_link(ng, input_node.outputs.get("Diffuse Map"), add_env.inputs[1])
        safe_link(ng, input_node.outputs.get("Environment Map"), add_env.inputs[2])
        
        safe_link(ng, input_node.outputs.get("Opacity"), math_op_scale.inputs[0])
        safe_link(ng, math_op_scale.outputs[0], math_alpha.inputs[0])
        safe_link(ng, input_node.outputs.get("Alpha Map"), math_alpha.inputs[1])
        
        safe_link(ng, add_env.outputs[0], principled.inputs["Base Color"])
        safe_link(ng, math_alpha.outputs[0], principled.inputs["Alpha"]) 
        # Emission connection removed
        
        safe_link(ng, principled.outputs[0], output_node.inputs["BSDF"])
    
    return ng

class LS3D_OT_AddEnvSetup(bpy.types.Operator):
    """Add LS3D Environment shader nodes with a frame"""
    bl_idname = "node.add_ls3d_env_setup"
    bl_label = "Add LS3D Environment"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or not obj.active_material:
            self.report({'ERROR'}, "No active material found.")
            return {'CANCELLED'}
            
        mat = context.object.active_material
        if not mat.use_nodes:
            mat.use_nodes = True
        
        tree = mat.node_tree
        nodes = tree.nodes
        links = tree.links
        
        # 1. Find existing LS3D node to connect to
        ls3d_node = next((n for n in nodes if n.type == 'GROUP' and n.node_tree and "LS3D Material Data" in n.node_tree.name), None)

        # 2. Determine Location
        start_x = -1500
        start_y = 300
        if ls3d_node:
            start_x = ls3d_node.location.x - 1300
            start_y = ls3d_node.location.y - 200

        # 3. Create the Frame
        frame = nodes.new('NodeFrame')
        frame.label = "LS3D Environment Setup"
        frame.location = (start_x, start_y)
        frame.use_custom_color = True
        frame.color = (0.2, 0.5, 0.4) 
        
        # 4. Create nodes
        coord = nodes.new('ShaderNodeTexCoord')
        coord.location = (start_x + 50, start_y - 50)
        coord.parent = frame
        
        mapping = nodes.new('ShaderNodeMapping')
        mapping.vector_type = 'TEXTURE'
        mapping.location = (start_x + 250, start_y - 50)
        mapping.parent = frame
        
        tex_image = nodes.new('ShaderNodeTexImage')
        tex_image.projection = 'SPHERE' 
        tex_image.label = "Environment Map"
        tex_image.location = (start_x + 450, start_y - 50)
        tex_image.parent = frame
        
        env_group_data = get_or_create_env_group()
        env_group = nodes.new('ShaderNodeGroup')
        env_group.node_tree = env_group_data
        env_group.location = (start_x + 750, start_y - 50)
        env_group.parent = frame
        
        # 5. Connections
        # FIXED: "Reflection" is the hardcoded name in Blender's TexCoord node
        links.new(coord.outputs["Reflection"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex_image.inputs["Vector"])
        links.new(tex_image.outputs["Color"], env_group.inputs["Color"])
        
        if ls3d_node:
            if "Environment Map" in ls3d_node.inputs:
                links.new(env_group.outputs["Output"], ls3d_node.inputs["Environment Map"])
        
        mat.ls3d_env_enabled = True
        
        for n in nodes: n.select = False
        tex_image.select = True
        nodes.active = tex_image
        
        return {'FINISHED'}
    
class LS3D_OT_AddNode(bpy.types.Operator):
    """Add LS3D Material Data Node to the current material"""
    bl_idname = "node.add_ls3d_group"
    bl_label = "Add LS3D Node"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or not obj.active_material:
            self.report({'ERROR'}, "No active object or material found.")
            return {'CANCELLED'}
            
        mat = obj.active_material
        if not mat.use_nodes:
            mat.use_nodes = True
            
        tree = mat.node_tree
        group_data = get_or_create_ls3d_group()
        
        # Create the Group Node
        group_node = tree.nodes.new('ShaderNodeGroup')
        group_node.node_tree = group_data
        group_node.location = (-300, 200)
        group_node.width = 240
        
        # Deselect all and select new node
        for n in tree.nodes:
            n.select = False
        group_node.select = True
        tree.nodes.active = group_node
        
        return {'FINISHED'}

class The4DSExporter:
    def __init__(self, filepath, objects):
        self.filepath = filepath
        self.objects_to_export = objects
        self.materials = []
        self.objects = []
        self.version = VERSION_MAFIA
        self.frames_map = {}
        self.joint_map = {}
        self.frame_index = 1
        self.lod_map = {}
    def write_string(self, f, string):
        # Encode as Windows-1250
        try:
            encoded = string.encode("windows-1250", errors="replace")
        except:
            encoded = string.encode("ascii", errors="replace")
            
        # Hard limit 255 chars (1 byte length)
        if len(encoded) > 255:
            encoded = encoded[:255]
            
        f.write(struct.pack("B", len(encoded)))
        if len(encoded) > 0:
            f.write(encoded)
    def serialize_header(self, f):
        f.write(b"4DS\0")
        f.write(struct.pack("<H", self.version))
        now = datetime.now()
        epoch = datetime(1601, 1, 1)
        delta = now - epoch
        filetime = int(delta.total_seconds() * 1e7)
        f.write(struct.pack("<Q", filetime))
    def collect_materials(self):
        materials = set()
        for obj in self.objects_to_export:
            if obj.type == 'MESH':
                for slot in obj.material_slots:
                    if slot.material:
                        materials.add(slot.material)
        return list(materials)
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
    
    
                
    def serialize_singlemesh(self, f, obj, num_lods):
        armature_mod = next((m for m in obj.modifiers if m.type == 'ARMATURE'), None)
        if not armature_mod or not armature_mod.object:
            return
        armature = armature_mod.object
        bones = list(armature.data.bones)
        total_verts = len(obj.data.vertices)
        for _ in range(num_lods):
            f.write(struct.pack("<B", len(bones)))
            # Unweighted verts count (assigned to root)
            weighted_verts = set()
            for v in obj.data.vertices:
                if any(g.weight > 0.0 for g in v.groups):
                    weighted_verts.add(v.index)
            unweighted_count = total_verts - len(weighted_verts)
            f.write(struct.pack("<I", unweighted_count))
            # Mesh bounds
            coords = [v.co for v in obj.data.vertices]
            min_b = Vector((min(c[i] for c in coords) for i in range(3)))
            max_b = Vector((max(c[i] for c in coords) for i in range(3)))
            f.write(struct.pack("<3f", min_b.x, min_b.z, min_b.y))
            f.write(struct.pack("<3f", max_b.x, max_b.z, max_b.y))
            for bone_idx, bone in enumerate(bones):
                # Inverse bind pose
                mat = bone.matrix_local.copy()
                # Y/Z swap for Mafia coord system
                mat = mat @ Matrix([[1,0,0,0], [0,0,1,0], [0,1,0,0], [0,0,0,1]])
                inv = mat.inverted()
                # Row-major flatten
                flat = [inv[i][j] for i in range(4) for j in range(4)]
                f.write(struct.pack("<16f", *flat))
                vg = obj.vertex_groups.get(bone.name)
                if not vg:
                    f.write(struct.pack("<4I", 0, 0, bone_idx, 0))
                    f.write(struct.pack("<6f", min_b.x, min_b.z, min_b.y, max_b.x, max_b.z, max_b.y))
                    continue
                locked = []
                weighted = []
                weights = []
                for v_idx in range(total_verts):
                    try:
                        weight = vg.weight(v_idx)
                    except RuntimeError:
                        continue
                    if weight >= 0.999:
                        locked.append(v_idx)
                    elif weight > 0.001:
                        weighted.append(v_idx)
                        weights.append(weight)
                f.write(struct.pack("<I", len(locked)))
                f.write(struct.pack("<I", len(weighted)))
                f.write(struct.pack("<I", bone_idx))
                f.write(struct.pack("<3f", min_b.x, min_b.z, min_b.y))
                f.write(struct.pack("<3f", max_b.x, max_b.z, max_b.y))
                for w in weights:
                    f.write(struct.pack("<f", w))
                    
    def serialize_morph(self, f, obj, num_lods):
        shape_keys = obj.data.shape_keys
        if not shape_keys or len(shape_keys.key_blocks) <= 1:
            f.write(struct.pack("<B", 0))
            return
        morph_data = {}
        for key in shape_keys.key_blocks[1:]:
            parts = key.name.split("_")
            if len(parts) >= 2 and parts[0] == "Target":
                try:
                    target_idx = int(parts[1])
                    lod_idx = 0
                    channel_idx = 0
                    for part in parts[2:]:
                        if part.startswith("LOD"):
                            lod_idx = int(part[3:])
                        elif part.startswith("Channel"):
                            channel_idx = int(part[7:])
                    if lod_idx < num_lods:
                        morph_data.setdefault(lod_idx, {}).setdefault(channel_idx, []).append((target_idx, key))
                except:
                    continue
        num_targets = max((len(targets) for lod in morph_data.values() for targets in lod.values()), default=1)
        num_channels = max((len(lod) for lod in morph_data.values()), default=1)
        f.write(struct.pack("<B", num_targets))
        f.write(struct.pack("<B", num_channels))
        f.write(struct.pack("<B", num_lods))
        for lod_idx in range(num_lods):
            for channel_idx in range(num_channels):
                targets = morph_data.get(lod_idx, {}).get(channel_idx, [])
                num_vertices = len(obj.data.vertices)
                f.write(struct.pack("<H", num_vertices))
                for vert_idx in range(num_vertices):
                    for target_idx in range(num_targets):
                        target_key = next((k for t, k in targets if t == target_idx), None)
                        pos = target_key.data[vert_idx].co if target_key else obj.data.vertices[vert_idx].co
                        norm = obj.data.vertices[vert_idx].normal
                        f.write(struct.pack("<3f", pos.x, pos.z, pos.y))
                        f.write(struct.pack("<3f", norm.x, norm.z, norm.y))
                f.write(struct.pack("<?", False))
            bounds = [v.co for v in obj.data.vertices]
            min_bounds = Vector((min(v.x for v in bounds), min(v.y for v in bounds), min(v.z for v in bounds)))
            max_bounds = Vector((max(v.x for v in bounds), max(v.y for v in bounds), max(v.z for v in bounds)))
            center = (min_bounds + max_bounds) / 2
            dist = (max_bounds - min_bounds).length
            f.write(struct.pack("<3f", min_bounds.x, min_bounds.z, min_bounds.y))
            f.write(struct.pack("<3f", max_bounds.x, max_bounds.z, max_bounds.y))
            f.write(struct.pack("<3f", center.x, center.z, center.y))
            f.write(struct.pack("<f", dist))
    
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
        f.write(struct.pack("<H", 0))
        link_ids = obj.get("link_ids", [])
        f.write(struct.pack("<B", len(link_ids)))
        if link_ids:
            f.write(struct.pack(f"<{len(link_ids)}H", *link_ids))

    def serialize_occluder(self, f, obj):
        # 1. Prepare Evaluated Mesh
        # Occluder geometry is stored in LOCAL space. 
        # The Frame Transform (Matrix) handles world position.
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)
            bm = bmesh.new()
            bm.from_mesh(eval_obj.to_mesh())
        except:
            bm = bmesh.new()
            bm.from_mesh(obj.data)

        # 2. Triangulate (Required)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        # 3. Write Counts (uint32)
        f.write(struct.pack("<I", len(bm.verts)))
        f.write(struct.pack("<I", len(bm.faces)))
        
        # 4. Write Vertices
        # Swap Y/Z for Mafia Space
        for v in bm.verts:
            f.write(struct.pack("<3f", v.co.x, v.co.z, v.co.y))
            
        # 5. Write Faces
        # Swap Winding (0, 2, 1)
        for face in bm.faces:
            fv = face.verts
            f.write(struct.pack("<3H", fv[0].index, fv[2].index, fv[1].index))
            
        # Cleanup
        bm.free()
        try:
            if 'eval_obj' in locals():
                eval_obj.to_mesh_clear()
        except:
            pass
        
    def serialize_joint(self, f, bone, armature, parent_id):
        matrix = bone.matrix_local.copy()
        matrix[1], matrix[2] = matrix[2].copy(), matrix[1].copy()
        flat = [matrix[i][j] for i in range(4) for j in range(3)]
        f.write(struct.pack("<12f", *flat))
        bone_idx = list(armature.data.bones).index(bone)
        f.write(struct.pack("<I", bone_idx))
    
    def serialize_frame(self, f, obj):
        # 1. IDENTIFY FRAME TYPE
        frame_type_str = getattr(obj, "ls3d_frame_type", '1')
        frame_type = int(frame_type_str)
        
        # Auto-detect Sector
        if obj.type == 'MESH' and "sector" in obj.name.lower():
            frame_type = FRAME_SECTOR

        # --- CRITICAL FIX: SKIP PORTALS ---
        # Portals are Type 5 (Sector) for UI reasons, but they are NOT frames.
        # They are data blocks written inside their parent Sector.
        is_portal_name = bool(re.search(r"_portal\d+$", obj.name, re.IGNORECASE))
        if frame_type == FRAME_SECTOR and is_portal_name:
            # Verify it has a parent that is also a sector/compatible
            if obj.parent: 
                # Skip this frame, it's already handled by serialize_sector
                return

        visual_type = 0
        visual_flags = (0, 0)
        
        if frame_type == FRAME_VISUAL:
            r_flag1 = getattr(obj, "render_flags", 0)
            r_flag2 = getattr(obj, "render_flags2", 0)
            visual_flags = (r_flag1, r_flag2)
            
            if obj.type == "MESH":
                if hasattr(obj, "visual_type"):
                    visual_type = int(obj.visual_type)
                    if visual_type in (VISUAL_SINGLEMESH, VISUAL_SINGLEMORPH):
                        if not any(m.type == 'ARMATURE' and m.object for m in obj.modifiers): 
                            visual_type = VISUAL_OBJECT 
                else:
                    if obj.modifiers and any(mod.type == "ARMATURE" for mod in obj.modifiers):
                        visual_type = VISUAL_SINGLEMESH
                    elif obj.data.shape_keys: visual_type = VISUAL_MORPH
        
        # 2. HIERARCHY & MATRIX CALCULATION
        parent_id = 0
        
        # Start with the object's World Matrix
        matrix_to_write = obj.matrix_world.copy()
        
        if obj.parent:
            # Case A: Parent is a Bone
            if obj.parent_type == 'BONE' and obj.parent_bone: 
                if obj.parent_bone in self.joint_map:
                    parent_id = self.joint_map[obj.parent_bone]
                    arm = obj.parent
                    bone = arm.data.bones[obj.parent_bone]
                    parent_matrix = arm.matrix_world @ bone.matrix_local
                    matrix_to_write = parent_matrix.inverted() @ obj.matrix_world
            
            # Case B: Parent is an Object
            elif obj.parent in self.frames_map: 
                parent_id = self.frames_map[obj.parent]
                
                # Check Parent Type
                is_parent_sector = False
                p_type_str = getattr(obj.parent, "ls3d_frame_type", '1')
                if int(p_type_str) == FRAME_SECTOR:
                    is_parent_sector = True
                elif "sector" in obj.parent.name.lower():
                    is_parent_sector = True
                
                if is_parent_sector:
                    # CASE 1: Parent is a SECTOR -> Use WORLD Coordinates
                    # Sectors are at 0,0,0 in 4DS.
                    matrix_to_write = obj.matrix_world
                else:
                    # CASE 2: Parent is Standard -> Use LOCAL Coordinates
                    matrix_to_write = obj.parent.matrix_world.inverted() @ obj.matrix_world
        
        self.frames_map[obj] = self.frame_index
        self.frame_index += 1
        
        # 3. DECOMPOSE & PREPARE VALUES
        pos = matrix_to_write.to_translation()
        rot = matrix_to_write.to_quaternion()
        scale = matrix_to_write.to_scale()
        
        cull_flags = getattr(obj, "cull_flags", 0)
        
        # CASE 3: Current Object IS A SECTOR -> Force Identity
        if frame_type == FRAME_SECTOR:
            pos = Vector((0, 0, 0))
            rot = Quaternion((1, 0, 0, 0))
            scale = Vector((1, 1, 1))
            if cull_flags == 0: cull_flags = 125

        # 4. WRITE HEADER
        f.write(struct.pack("<B", frame_type))
        if frame_type == FRAME_VISUAL:
            f.write(struct.pack("<B", visual_type))
            f.write(struct.pack("<2B", *visual_flags))
            
        f.write(struct.pack("<H", parent_id))
        
        # 5. WRITE TRANSFORM (Swap Blender Y/Z -> Mafia Y/Z)
        f.write(struct.pack("<3f", pos.x, pos.z, pos.y))
        f.write(struct.pack("<3f", scale.x, scale.z, scale.y))
        f.write(struct.pack("<4f", rot.w, rot.x, rot.z, rot.y))
        
        f.write(struct.pack("<B", cull_flags))
        
        self.write_string(f, obj.name)
        self.write_string(f, getattr(obj, "ls3d_user_props", ""))
        
        # 6. WRITE BODY
        if frame_type == FRAME_VISUAL and obj.type == 'MESH':
            lods = self.lod_map.get(obj, [obj])
            num = self.serialize_object(f, obj, lods)
            
            if visual_type == VISUAL_BILLBOARD: self.serialize_billboard(f, obj)
            elif visual_type == VISUAL_MIRROR: self.serialize_mirror(f, obj)
            elif visual_type == VISUAL_SINGLEMESH: self.serialize_singlemesh(f, obj, num)
            elif visual_type == VISUAL_SINGLEMORPH: 
                self.serialize_singlemesh(f, obj, num)
                self.serialize_morph(f, obj, num)
            elif visual_type == VISUAL_MORPH: self.serialize_morph(f, obj, num)

        elif frame_type == FRAME_SECTOR: self.serialize_sector(f, obj)
        elif frame_type == FRAME_DUMMY: self.serialize_dummy(f, obj)
        elif frame_type == FRAME_TARGET: self.serialize_target(f, obj)
        elif frame_type == FRAME_OCCLUDER: self.serialize_occluder(f, obj)
        
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
        # 1. Flags (2x Int32)
        f1 = getattr(obj, "ls3d_sector_flags1", 0)
        f2 = getattr(obj, "ls3d_sector_flags2", 0)
        f.write(struct.pack("<2i", f1, f2))
        
        # 2. Geometry Prep
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)
            bm = bmesh.new()
            bm.from_mesh(eval_obj.to_mesh())
        except:
            bm = bmesh.new()
            bm.from_mesh(obj.data)

        # Triangulate (Mandatory)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        num_verts = len(bm.verts)
        num_faces = len(bm.faces)
        
        f.write(struct.pack("<I", num_verts))
        f.write(struct.pack("<I", num_faces))
        
        # 3. Vertices (World Space, XZY) & Bounds
        min_b = [float('inf')] * 3
        max_b = [float('-inf')] * 3
        
        world_mat = obj.matrix_world
        
        for v in bm.verts:
            v_world = world_mat @ v.co
            # Coordinate Swap: Blender (X, Y, Z) -> Mafia (X, Z, Y)
            vx, vy, vz = v_world.x, v_world.z, v_world.y
            
            f.write(struct.pack("<3f", vx, vy, vz))
            
            if vx < min_b[0]: min_b[0] = vx
            if vy < min_b[1]: min_b[1] = vy
            if vz < min_b[2]: min_b[2] = vz
            if vx > max_b[0]: max_b[0] = vx
            if vy > max_b[1]: max_b[1] = vy
            if vz > max_b[2]: max_b[2] = vz

        # 4. Faces (Swapped Winding: 0, 2, 1)
        for face in bm.faces:
            fv = face.verts
            f.write(struct.pack("<3H", fv[0].index, fv[2].index, fv[1].index))
            
        bm.free()
        
        # 5. Bounding Box (Written AFTER faces in v29)
        if num_verts > 0:
            f.write(struct.pack("<3f", *min_b))
            f.write(struct.pack("<3f", *max_b))
        else:
            f.write(struct.pack("<6f", 0,0,0, 0,0,0))
            
        # 6. Portals
        portals = []
        for child in obj.children:
            if re.search(r"_portal\d+$", child.name, re.IGNORECASE):
                portals.append(child)
        portals.sort(key=lambda x: x.name)
        
        f.write(struct.pack("<B", len(portals)))
        for p_obj in portals:
            self.serialize_portal(f, p_obj)

    def serialize_portal(self, f, obj):
        # 1. Get Geometry
        verts, normal, center = self.get_ordered_portal_verts(obj)
        
        if len(verts) < 3:
            f.write(struct.pack("<B", 0))    # nVerts
            f.write(struct.pack("<I", 0))    # Flags
            f.write(struct.pack("<8f", 0,0,0,0,0,0,0,0)) # Near, Far, D, Normal
            return

        # 2. Transform to Mafia Space (X, Z, Y)
        mafia_verts = [Vector((v.x, v.z, v.y)) for v in verts]
        mafia_normal = Vector((normal.x, normal.z, normal.y))
        mafia_point = mafia_verts[0]
        
        # 3. Calculate Math (Max4ds Logic)
        stored_normal = -mafia_normal
        stored_d = mafia_point.dot(mafia_normal)
        
        # 4. Get Properties
        flags = getattr(obj, "ls3d_portal_flags", 0)
        near = getattr(obj, "ls3d_portal_near", 0.0)
        far = getattr(obj, "ls3d_portal_far", 0.0)
        
        # 5. WRITE STRUCTURE
        
        # A. Count (1 byte)
        f.write(struct.pack("<B", len(mafia_verts)))
        
        # B. Flags (4 bytes)
        f.write(struct.pack("<I", flags))
        
        # C. Ranges (4 bytes each)
        f.write(struct.pack("<f", near))
        f.write(struct.pack("<f", far))
        
        # D. Plane (16 bytes)
        # Normal (3 floats), D (float)
        f.write(struct.pack("<3f", stored_normal.x, stored_normal.y, stored_normal.z))
        f.write(struct.pack("<f", stored_d))
        
        # E. Vertices
        verts_portal = list(mafia_verts)
        
        for v in verts_portal:
            f.write(struct.pack("<3f", v.x, v.y, v.z))

    def serialize_material(self, f, mat, mat_index):
        # 1. Flags (Masking Signed->Unsigned)
        signed_flags = mat.ls3d_material_flags
        flags = signed_flags & 0xFFFFFFFF
        f.write(struct.pack("<I", flags))

        # 2. Colors
        amb = getattr(mat, "ls3d_ambient_color", (0.5,0.5,0.5))
        dif = getattr(mat, "ls3d_diffuse_color", (1,1,1))
        emi = getattr(mat, "ls3d_emission_color", (0,0,0))
        
        # 3. Retrieve Opacity & Textures from Nodes
        opacity = 1.0
        env_intensity = 0.0
        diff_tex = ""
        alpha_tex = ""
        env_tex = ""

        if mat.use_nodes:
            main_node = None
            for n in mat.node_tree.nodes:
                if n.type == 'GROUP' and n.node_tree and "LS3D Material Data" in n.node_tree.name:
                    main_node = n
                    break
            
            if main_node:
                # Get Opacity from Node Input
                if "Opacity" in main_node.inputs:
                    opacity = main_node.inputs["Opacity"].default_value / 100.0
                
                def find_image(socket_name):
                    if socket_name not in main_node.inputs: return None, None
                    socket = main_node.inputs[socket_name]
                    if not socket.is_linked: return None, None
                    link_node = socket.links[0].from_node
                    if link_node.type == 'TEX_IMAGE' and link_node.image:
                        return link_node, None
                    if link_node.type == 'GROUP' and link_node.node_tree and "LS3D Environment" in link_node.node_tree.name:
                        return None, link_node 
                    return None, None

                d_node, _ = find_image("Diffuse Map")
                if d_node: diff_tex = os.path.basename(d_node.image.filepath or d_node.image.name)
                
                a_node, _ = find_image("Alpha Map")
                if a_node: alpha_tex = os.path.basename(a_node.image.filepath or a_node.image.name)
                
                _, env_grp_node = find_image("Environment Map")
                if env_grp_node:
                    if "Intensity" in env_grp_node.inputs:
                        env_intensity = env_grp_node.inputs["Intensity"].default_value
                    if "Color" in env_grp_node.inputs and env_grp_node.inputs["Color"].is_linked:
                        img_node = env_grp_node.inputs["Color"].links[0].from_node
                        if img_node.type == 'TEX_IMAGE' and img_node.image:
                            env_tex = os.path.basename(img_node.image.filepath or img_node.image.name)

        f.write(struct.pack("<3f", *amb))
        f.write(struct.pack("<3f", *dif))
        f.write(struct.pack("<3f", *emi))
        f.write(struct.pack("<f", opacity))

        # 4. Write Texture Block
        has_env = (flags & MTL_ENV_ENABLE) != 0
        has_diff = (flags & MTL_DIFFUSE_ENABLE) != 0
        has_alpha_tex = (flags & MTL_ALPHA_ENABLE) and (flags & MTL_ALPHATEX)

        if has_env:
            f.write(struct.pack("<f", env_intensity))
            self.write_string(f, env_tex.upper())

        if has_diff:
            self.write_string(f, diff_tex.upper())

        if has_alpha_tex:
            self.write_string(f, alpha_tex.upper())

        # Padding Byte logic: 
        # Only write 0 if NO Diffuse AND NO Alpha Texture strings were written.
        # Env Map does not count.
        if not has_diff and not has_alpha_tex:
            f.write(struct.pack("B", 0))

        # 5. Anim Data (Exclusive Write + Masking)
        if flags & MTL_ALPHA_ANIMATED:
            f.write(struct.pack("<I", mat.ls3d_alpha_anim_frames & 0xFFFFFFFF))
            f.write(struct.pack("<H", 0))
            f.write(struct.pack("<I", mat.ls3d_alpha_anim_period & 0xFFFFFFFF))
            f.write(struct.pack("<Q", 0))

        elif flags & MTL_DIFFUSE_ANIMATED:
            f.write(struct.pack("<I", mat.ls3d_diffuse_anim_frames & 0xFFFFFFFF))
            f.write(struct.pack("<H", 0))
            f.write(struct.pack("<I", mat.ls3d_diffuse_anim_period & 0xFFFFFFFF))
            f.write(struct.pack("<Q", 0))

    def serialize_object(self, f, obj, lods):
        """
        Serializes the geometry block for an object (FRAME_VISUAL).
        Uses Blender's native mesh data to ensure robust indexing.
        Fixed for Blender 5.0 (removed calc_normals_split).
        """

        # InstanceID: 0 = Unique Geometry (Source)
        f.write(struct.pack("<H", 0))

        # LOD Count
        f.write(struct.pack("<B", len(lods)))
        
        # Reset mappings for this object
        self.current_lod_mappings = [] 
        self.current_lod_counts = []

        for lod_idx, lod_obj in enumerate(lods):
            # --- 1. HANDLE FADE DISTANCE ---
            dist = getattr(lod_obj, "ls3d_lod_dist", 0.0)
            f.write(struct.pack("<f", float(dist)))
            
            # --- 2. MESH PROCESSING & PREPARATION ---
            try:
                # Get the evaluated mesh with all modifiers applied
                depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_obj = lod_obj.evaluated_get(depsgraph)
                temp_mesh = eval_obj.to_mesh()
            except Exception as e:
                print(f"LS3D Error: Failed to evaluate mesh '{lod_obj.name}': {e}")
                # Fallback to data if evaluation fails (rare)
                temp_mesh = lod_obj.data.copy()

            # Generate loop triangles (Face triangulation data)
            # In Blender 5.0, normals are already calculated on the eval mesh
            temp_mesh.calc_loop_triangles()

            uv_layer = temp_mesh.uv_layers.active # Get active UV layer
            
            # Collect Loop Data (Normals & UVs)
            # We map Vertex Index -> {Normal, UV}
            # Note: This approach assumes 1 set of UV/Normal per vertex (Hard Seams split vertices in game engines usually)
            # For 4DS, if we strictly use mesh.vertices, we are sharing attributes.
            vertex_loop_data = {} 
            for loop in temp_mesh.loops:
                v_idx = loop.vertex_index
                if v_idx not in vertex_loop_data:
                    # Get UV (Flip V for Mafia: 1.0 - V)
                    u, v_coord = (0.0, 0.0)
                    if uv_layer:
                        uv_coords = uv_layer.data[loop.index].uv
                        u, v_coord = uv_coords.x, 1.0 - uv_coords.y
                    
                    # loop.normal contains the split normal (smooth/sharp)
                    vertex_loop_data[v_idx] = {
                        'norm': loop.normal, 
                        'uv': (u, v_coord)
                    }

            # Map for morph targets (Identity, since we use 1:1 vertex list)
            identity_vert_map = {v.index: [v.index] for v in temp_mesh.vertices}
            self.current_lod_mappings.append(identity_vert_map)
            self.current_lod_counts.append(len(temp_mesh.vertices))

            # --- 3. WRITE VERTEX DATA ---
            num_exported_verts = len(temp_mesh.vertices)
            
            # Check Limits (UInt16 = 65535)
            if num_exported_verts > 65535:
                print(f"LS3D Error: Object '{lod_obj.name}' has {num_exported_verts} vertices (Limit 65535).")
                eval_obj.to_mesh_clear()
                return 0 
                
            f.write(struct.pack("<H", num_exported_verts))
            
            for v_idx, vert in enumerate(temp_mesh.vertices):
                pos = vert.co
                
                # Fetch attributes
                if v_idx in vertex_loop_data:
                    norm = vertex_loop_data[v_idx]['norm']
                    uv = vertex_loop_data[v_idx]['uv']
                else:
                    norm = vert.normal 
                    uv = (0.0, 0.0)

                # Coordinate Swap: Blender (X, Y, Z) -> Mafia (X, Z, Y)
                f.write(struct.pack("<3f", pos.x, pos.z, pos.y))
                f.write(struct.pack("<3f", norm.x, norm.z, norm.y))
                f.write(struct.pack("<2f", uv[0], uv[1]))
            
            # --- 4. WRITE FACE DATA ---
            # Group triangles by Material Index
            mat_triangle_groups = {} 
            for tri in temp_mesh.loop_triangles:
                mat_idx = tri.material_index
                if mat_idx < 0: mat_idx = 0 
                mat_triangle_groups.setdefault(mat_idx, []).append(tri.vertices)
            
            num_material_groups = len(mat_triangle_groups)
            f.write(struct.pack("<B", num_material_groups))
            
            # Sort keys to ensure deterministic export order
            sorted_mat_indices = sorted(mat_triangle_groups.keys())

            for mat_idx in sorted_mat_indices:
                triangles = mat_triangle_groups[mat_idx]
                
                f.write(struct.pack("<H", len(triangles)))
                
                for tri_verts in triangles: 
                    # Winding Swap: (0, 1, 2) -> (0, 2, 1)
                    f.write(struct.pack("<3H", tri_verts[0], tri_verts[2], tri_verts[1]))
                
                # Resolve Material ID (1-based)
                mat_id = 0
                if 0 <= mat_idx < len(lod_obj.material_slots):
                    real_mat = lod_obj.material_slots[mat_idx].material
                    if real_mat in self.materials:
                        mat_id = self.materials.index(real_mat) + 1
                f.write(struct.pack("<H", mat_id))
            
            # Cleanup
            eval_obj.to_mesh_clear()
            
        return len(lods)
    
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
        # Bounds
        min_b = getattr(obj, "bbox_min", (-1,-1,-1))
        max_b = getattr(obj, "bbox_max", (1,1,1))
        f.write(struct.pack("<3f", min_b[0], min_b[2], min_b[1]))
        f.write(struct.pack("<3f", max_b[0], max_b[2], max_b[1]))
        
        # Center/Radius
        f.write(struct.pack("<3f", 0,0,0)) 
        f.write(struct.pack("<f", 10.0))
        
        # Matrix (Identity)
        m = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
        f.write(struct.pack("<16f", *m))
        
        # Color
        col = getattr(obj, "mirror_color", (0,0,0))
        f.write(struct.pack("<3f", *col))
        
        # Dist
        f.write(struct.pack("<f", getattr(obj, "mirror_dist", 100.0)))
        
        # Mesh
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        f.write(struct.pack("<I", len(bm.verts)))
        f.write(struct.pack("<I", len(bm.faces)))
        for v in bm.verts:
            f.write(struct.pack("<3f", v.co.x, v.co.z, v.co.y))
        for face in bm.faces:
            f.write(struct.pack("<3H", face.verts[0].index, face.verts[2].index, face.verts[1].index))
        bm.free()

    def serialize_joints(self, f, armature):
        # We don't write the Armature Object itself as a frame, 
        # but we need to pass its hierarchy context.
        # Parent ID for the root bone is the Armature's parent (if any).
        
        arm_parent_id = 0
        if armature.parent:
             arm_parent_id = self.frames_map.get(armature.parent, 0)
        
        # Iterate bones
        for bone in armature.data.bones:
            frame_type = FRAME_JOINT
            
            # Determine Parent ID
            if bone.parent:
                parent_id = self.joint_map.get(bone.parent.name, 0)
            else:
                # Root bone connects to Armature's parent
                parent_id = arm_parent_id
            
            # Register this bone
            self.joint_map[bone.name] = self.frame_index
            self.frame_index += 1
            
            # Calculate Transform
            if bone.parent:
                matrix = bone.parent.matrix_local.inverted() @ bone.matrix_local
            else:
                matrix = bone.matrix_local
            
            pos = matrix.to_translation()
            rot = matrix.to_quaternion()
            scale = matrix.to_scale()
            
            f.write(struct.pack("<B", frame_type))
            f.write(struct.pack("<H", parent_id))
            f.write(struct.pack("<3f", pos.x, pos.z, pos.y))
            f.write(struct.pack("<3f", scale.x, scale.z, scale.y))
            f.write(struct.pack("<4f", rot.w, rot.x, rot.z, rot.y))
            f.write(struct.pack("<B", 0)) # Joint flags (unused?)
            self.write_string(f, bone.name)
            self.write_string(f, "") # User props
            
            # Joint Body
            self.serialize_joint(f, bone, armature, parent_id)
            
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
    
    def serialize_file(self):
        with open(self.filepath, "wb") as f:
            self.serialize_header(f)
            
            # 1. Materials
            self.materials = self.collect_materials()
            f.write(struct.pack("<H", len(self.materials)))
            for i, mat in enumerate(self.materials):
                self.serialize_material(f, mat, i + 1)
            
            # 2. Identify Special Objects
            lod_objects_set = self.collect_lods()
            
            # Filter Portals (They are data blocks, not Frames)
            portal_objects = set()
            for obj in self.objects_to_export:
                if re.search(r"_portal\d+$", obj.name, re.IGNORECASE):
                    if obj.parent and getattr(obj.parent, "ls3d_frame_type", '1') == '5':
                        portal_objects.add(obj)

            # 3. Build Main Frame List
            scene_names = set(o.name for o in bpy.context.scene.objects)
            
            raw_objects = [
                obj for obj in self.objects_to_export
                if obj.name in scene_names 
                and obj not in lod_objects_set
                and obj not in portal_objects 
                and obj.type in ("MESH", "EMPTY", "ARMATURE")
            ]
            
            # 4. Hierarchy Sort
            self.objects = []
            roots = [o for o in raw_objects if (not o.parent) or (o.parent not in raw_objects)]
            roots.sort(key=lambda x: x.name)

            def sort_hierarchy(obj):
                if obj in self.objects: return 
                self.objects.append(obj)
                children = [c for c in obj.children if c in raw_objects]
                children.sort(key=lambda x: x.name)
                for child in children:
                    sort_hierarchy(child)

            for root in roots:
                sort_hierarchy(root)
            
            # Leftovers
            seen = set(self.objects)
            leftovers = [o for o in raw_objects if o not in seen]
            self.objects.extend(leftovers)

            # 5. Count Frames
            visual_frames_count = 0
            for obj in self.objects:
                if obj.type == "ARMATURE":
                    visual_frames_count += len(obj.data.bones)
                else:
                    visual_frames_count += 1
            
            f.write(struct.pack("<H", visual_frames_count))
            
            self.frame_index = 1
            self.frames_map = {} 
            self.joint_map = {}
            
            # 6. Write Frames
            for obj in self.objects:
                if obj.type == "ARMATURE":
                    self.serialize_joints(f, obj)
                else:
                    self.serialize_frame(f, obj)
            
            # Animation Flag
            is_anim = getattr(bpy.context.scene, "ls3d_is_animated", False)
            f.write(struct.pack("<?", is_anim))

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
            print(f"LS3D Warning: Provided texture path is invalid: {self.maps_dir}")
            self.maps_dir = None

        self.version = 0
        self.materials = []
        self.skinned_meshes = []
        self.frames_map = {}
        self.frame_index = 1
        self.joints = []
        self.bone_nodes = {}
        self.base_bone_name = None
        self.bones_map = {}
        self.armature = None
        self.parenting_info = []
        self.frame_types = {}
        self.frame_matrices = {}

    def get_or_load_texture(self, filename):
        if not self.maps_dir:
            return None
            
        base_name = os.path.basename(filename)
        norm_key = base_name.lower()
        
        if norm_key not in self.texture_cache:
            # Check ONLY in the maps_dir folder
            full_path = self.get_real_file_path(self.maps_dir, base_name)
            
            if full_path:
                try:
                    image = bpy.data.images.load(full_path, check_existing=True)
                    self.texture_cache[norm_key] = image
                except:
                    self.texture_cache[norm_key] = None
            else:
                self.texture_cache[norm_key] = None
                    
        return self.texture_cache[norm_key]

    def get_real_file_path(self, directory, filename):
        """Finds a file in a directory case-insensitively."""
        if not directory or not os.path.exists(directory):
            return None
            
        # Fast path: exact match
        exact_path = os.path.join(directory, filename)
        if os.path.exists(exact_path):
            return exact_path
            
        # Slow path: iterate directory
        filename_lower = filename.lower()
        try:
            for name in os.listdir(directory):
                if name.lower() == filename_lower:
                    return os.path.join(directory, name)
        except OSError:
            pass
            
        return None

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
                    return
                
                self.version = struct.unpack("<H", f.read(2))[0]
                if self.version != 29: # VERSION_MAFIA
                    print(f"Error: Unsupported 4DS version {self.version}. Only version 29 is supported.")
                    return
                
                f.read(8) # Skip Time

                # 2. Materials
                mat_count = struct.unpack("<H", f.read(2))[0]
                print(f"--- READING MATERIALS ({mat_count}) ---")
                
                self.materials = []
                for i in range(mat_count):
                    # Update Progress (First 30% of bar is materials)
                    wm.progress_update((i / mat_count) * 30)
                    
                    try:
                        mat = self.deserialize_material(f)
                        self.materials.append(mat)
                        
                        # LOGGING: Material Name and Flags
                        unsigned_flags = mat.ls3d_material_flags & 0xFFFFFFFF
                        print(f"  [Mat {i+1:03d}/{mat_count}] '{mat.name}' | Flags: {hex(unsigned_flags)}")
                        
                    except Exception as e:
                        print(f"  [Mat {i+1:03d}] ERROR: {e}")
                        # Append dummy to keep index alignment
                        self.materials.append(bpy.data.materials.new(f"Error_Mat_{i}"))

                # 3. Frames
                frame_count = struct.unpack("<H", f.read(2))[0]
                print(f"--- READING FRAMES ({frame_count}) ---")
                
                frames = []
                for i in range(frame_count):
                    # Update Progress (Remaining 70% of bar)
                    wm.progress_update(30 + ((i / frame_count) * 70))
                    
                    # LOGGING: Frame Index
                    print(f"  [Frame {i+1:03d}/{frame_count}] Processing...")
                    
                    if not self.deserialize_frame(f, self.materials, frames):
                        print(f"    !!! Failed to deserialize frame {i+1} !!!")
                        continue

                # 4. Post Processing
                print("--- POST PROCESSING ---")
                
                if self.armature and self.joints:
                    print("  > Building armature...")
                    self.build_armature()
                    print("  > Applying skinning...")
                    for mesh, vertex_groups, bone_to_parent in self.skinned_meshes:
                        self.apply_skinning(mesh, vertex_groups, bone_to_parent)
                
                print("  > Applying hierarchy...")
                self.apply_deferred_parenting()
                
                # Check EOF Animation Flag
                try:
                    f.seek(-1, 2) 
                    last_byte = f.read(1)
                    if last_byte:
                        val = struct.unpack("<B", last_byte)[0]
                        if val == 1:
                            bpy.context.scene.ls3d_is_animated = True
                            print("  > Animation flag: ACTIVE")
                        else:
                            bpy.context.scene.ls3d_is_animated = False
                            print("  > Animation flag: INACTIVE")
                except Exception as e:
                    print(f"  > Warning checking EOF flag: {e}")
                
                print(f"Import completed successfully: {filename}")

        except Exception as e:
            print(f"\nCRITICAL IMPORT ERROR: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # Cleanup UI state even if error occurs
            print("="*60)
            wm.progress_end()
            bpy.context.window.cursor_set("DEFAULT")

    def parent_to_bone(self, obj, bone_name):
        bpy.ops.object.select_all(action="DESELECT")
        self.armature.select_set(True)
        bpy.context.view_layer.objects.active = self.armature
        bpy.ops.object.mode_set(mode="EDIT")
        if bone_name not in self.armature.data.edit_bones:
            print(f"Error: Bone {bone_name} not found in armature during parenting")
            bpy.ops.object.mode_set(mode="OBJECT")
            return
        edit_bone = self.armature.data.edit_bones[bone_name]
        self.armature.data.edit_bones.active = edit_bone
        bone_matrix = Matrix(edit_bone.matrix)
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        self.armature.select_set(True)
        bpy.context.view_layer.objects.active = self.armature
        bone_matrix_tr = Matrix.Translation(bone_matrix.to_translation())
        obj.matrix_basis = self.armature.matrix_world @ bone_matrix_tr @ obj.matrix_basis
        bpy.ops.object.parent_set(type="BONE", xmirror=False, keep_transform=True)
    def read_string_fixed(self, f, length):
        bytes_data = f.read(length)
        unpacked = struct.unpack(f"{length}c", bytes_data)
        return "".join(c.decode("windows-1250", errors='replace') for c in unpacked)
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
    
    def get_color_key(self, filename):
        """
        Reads Index 0 from BMP palette (Offset 54).
        Returns linear RGB tuple.
        """
        if not self.maps_dir:
            return None
            
        # Clean filename just in case a path was passed
        base_name = os.path.basename(filename)
        full_path = self.get_real_file_path(self.maps_dir, base_name)
        
        if not full_path:
            return None
            
        try:
            with open(full_path, "rb") as f:
                # BMP Header
                if f.read(2) != b'BM': return None
                f.seek(28) # Bit count
                bit_count = struct.unpack("<H", f.read(2))[0]
                
                # Only 8-bit (256 colors) or lower have palettes
                if bit_count <= 8:
                    # Palette is usually at offset 54 (14 header + 40 info header)
                    f.seek(54)
                    # Read Index 0: Blue, Green, Red, Reserved
                    b, g, r, _ = struct.unpack("<BBBB", f.read(4))
                    
                    # Convert to Linear for Blender
                    def srgb_to_lin(c):
                        v = c / 255.0
                        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                        
                    return (srgb_to_lin(r), srgb_to_lin(g), srgb_to_lin(b))
        except Exception as e:
            print(f"Error reading Color Key from {full_path}: {e}")
            
        return None
    
    def set_material_data(
        self, material, diffuse, alpha_tex, env_tex, emission, opacity, metallic, use_color_key
    ):
        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        nodes.clear()
        
        # Create Group
        group_data = get_or_create_ls3d_group()
        group_node = nodes.new('ShaderNodeGroup')
        group_node.node_tree = group_data
        group_node.location = (0, 0)
        group_node.width = 240
        
        # Set Opacity Default Value
        if "Opacity" in group_node.inputs:
            group_node.inputs["Opacity"].default_value = opacity * 100.0

        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (300, 0)
        links.new(group_node.outputs["BSDF"], output.inputs["Surface"])
        
        # Diffuse
        if diffuse:
            diffuse = diffuse.lower()
            img = self.get_or_load_texture(diffuse)
            
            tex_node = nodes.new('ShaderNodeTexImage')
            tex_node.image = img
            tex_node.location = (-400, 100)
            tex_node.label = f"Diffuse: {diffuse}"
            
            if "Diffuse Map" in group_node.inputs:
                links.new(tex_node.outputs["Color"], group_node.inputs["Diffuse Map"])

            if use_color_key:
                tex_node.interpolation = 'Closest'
                material.blend_method = 'CLIP'

        # Alpha
        if alpha_tex:
            alpha_tex = alpha_tex.lower()
            img = self.get_or_load_texture(alpha_tex)
            
            a_node = nodes.new('ShaderNodeTexImage')
            a_node.image = img
            a_node.location = (-400, -200)
            a_node.label = f"Alpha: {alpha_tex}"
            if img:
                try: a_node.image.colorspace_settings.name = 'Non-Color'
                except: pass
            
            if "Alpha Map" in group_node.inputs:
                links.new(a_node.outputs["Color"], group_node.inputs["Alpha Map"])
            
            material.blend_method = 'BLEND'

        # Environment
        if env_tex:
            env_tex = env_tex.lower()
            img = self.get_or_load_texture(env_tex)
            
            frame = nodes.new('NodeFrame'); frame.label = "Environment Map"; frame.location = (-600, -500)
            coord = nodes.new('ShaderNodeTexCoord'); coord.location = (-1100, -500); coord.parent = frame
            mapping = nodes.new('ShaderNodeMapping'); mapping.location = (-900, -500); mapping.parent = frame
            
            env_img = nodes.new('ShaderNodeTexImage')
            env_img.image = img
            env_img.projection = 'SPHERE'
            env_img.location = (-700, -500)
            env_img.parent = frame
            
            env_grp_data = get_or_create_env_group()
            env_group = nodes.new('ShaderNodeGroup')
            env_group.node_tree = env_grp_data
            env_group.location = (-400, -500)
            env_group.parent = frame
            
            if "Intensity" in env_group.inputs:
                env_group.inputs["Intensity"].default_value = metallic 
            
            links.new(coord.outputs["Reflection"], mapping.inputs["Vector"])
            links.new(mapping.outputs["Vector"], env_img.inputs["Vector"])
            links.new(env_img.outputs["Color"], env_group.inputs["Color"])
            
            if "Environment Map" in group_node.inputs:
                links.new(env_group.outputs["Output"], group_node.inputs["Environment Map"])

        # Basic blend mode fallback (if just opacity scalar is low)
        if opacity < 1.0:
            material.blend_method = 'BLEND'

    def build_armature(self):
        if not self.armature or not self.joints:
            return
        bpy.context.view_layer.objects.active = self.armature
        bpy.ops.object.mode_set(mode="EDIT")
        armature = self.armature.data
        armature.display_type = "OCTAHEDRAL"
     
        # Key: Frame ID, Value: Blender Matrix
        world_matrices = {}
     
        # Base Bone (Root Identity)
        base_bone = armature.edit_bones[self.base_bone_name]
        world_matrices[1] = Matrix.Identity(4)
     
        bone_map = {self.base_bone_name: base_bone}
        # 1. Calculate World Matrices & Place Heads
        for name, local_matrix, parent_id, bone_id in self.joints:
            bone = armature.edit_bones.new(name)
            bone_map[name] = bone
         
            # Store scale for leaf calculation
            bone["file_scale"] = local_matrix.to_scale()
            # Logic: World = Parent_World @ Local
            parent_matrix = world_matrices.get(parent_id, Matrix.Identity(4))
         
            current_world_matrix = parent_matrix @ local_matrix
         
            # Store world matrix for children
            frame_index = -1
            for idx, fname in self.frames_map.items():
                if fname == name:
                    frame_index = idx
                    break
            if frame_index != -1:
                world_matrices[frame_index] = current_world_matrix
         
            # Apply Matrix (Sets Head and Orientation)
            bone.matrix = current_world_matrix
         
            # Parenting
            if parent_id == 1:
                bone.parent = base_bone
            else:
                parent_name = self.frames_map.get(parent_id)
                if isinstance(parent_name, str) and parent_name in bone_map:
                    bone.parent = bone_map[parent_name]
                else:
                    bone.parent = base_bone
        # 2. Fix Visuals (Prevent Collapsing)
        for bone in armature.edit_bones:
            if bone.name == self.base_bone_name:
                continue
            # Retrieve scale safely
            scl_prop = bone.get("file_scale")
            scl_vec = Vector(scl_prop) if scl_prop else Vector((1, 1, 1))
            max_scl = max(scl_vec.x, scl_vec.y, scl_vec.z)
            if max_scl < 0.01: max_scl = 1.0 # Prevent zero scale issues
            # Standard Bone Length
            target_length = 0.15 * max_scl
            if target_length < 0.05: target_length = 0.05
            # Get the forward direction from the matrix (Y-Axis is forward in Blender Bones)
            # We use this as a fallback if snapping fails
            matrix_forward = bone.matrix.to_quaternion() @ Vector((0, 1, 0))
            if bone.children:
                # Try snapping to average of children
                avg_child_head = Vector((0, 0, 0))
                for child in bone.children:
                    avg_child_head += child.head
                avg_child_head /= len(bone.children)
             
                # Check distance. If children are at the EXACT same spot as parent (pivot),
                # we must NOT snap, otherwise the parent collapses to a point.
                if (avg_child_head - bone.head).length > 0.001:
                    bone.tail = avg_child_head
                    bone.use_connect = True
                else:
                    # Fallback: Extend along the Rotation Axis
                    bone.tail = bone.head + matrix_forward * target_length
            else:
                # Leaf Bone: Always extend along the Rotation Axis
                bone.tail = bone.head + matrix_forward * target_length
        bpy.ops.object.mode_set(mode="OBJECT")
    def apply_skinning(self, mesh, vertex_groups, bone_to_parent):
        mod = mesh.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = self.armature
        total_vertices = len(mesh.data.vertices)
        vertex_counter = 0
        if vertex_groups:
            lod_vertex_groups = vertex_groups[0]
            bone_nodes = self.bone_nodes
            bone_names = sorted(
                bone_nodes.items(), key=lambda x: x[0]
            ) # Ensure order: [(0, "back1"), (1, "back2"), ...]
            bone_name_list = [
                name for _, name in bone_names
            ] # ["back1", "back2", "back3", "l_shoulder", ...]
            for bone_id, num_locked, weights in lod_vertex_groups:
                if bone_id < len(bone_name_list):
                    bone_name = bone_name_list[bone_id]
                else:
                    print(
                        f"Warning: Bone ID {bone_id} exceeds available bone names ({len(bone_name_list)})"
                    )
                    bone_name = f"unknown_bone_{bone_id}"
                bvg = mesh.vertex_groups.get(bone_name)
                if not bvg:
                    bvg = mesh.vertex_groups.new(name=bone_name)
                locked_vertices = list(
                    range(vertex_counter, vertex_counter + num_locked)
                )
                if locked_vertices:
                    bvg.add(locked_vertices, 1.0, "ADD")
                vertex_counter += num_locked
                weighted_vertices = list(
                    range(vertex_counter, vertex_counter + len(weights))
                )
                for i, w in zip(weighted_vertices, weights):
                    if i < total_vertices:
                        bvg.add([i], w, "REPLACE")
                    else:
                        print(
                            f"Warning: Vertex index {i} out of range ({total_vertices})"
                        )
                vertex_counter += len(weights)
            base_vg = mesh.vertex_groups.get(self.base_bone_name)
            if not base_vg:
                base_vg = mesh.vertex_groups.new(name=self.base_bone_name)
            base_vertices = list(range(vertex_counter, total_vertices))
            if base_vertices:
                base_vg.add(base_vertices, 1.0, "ADD")
    
    def deserialize_singlemesh(self, f, num_lods, mesh):
        armature_name = mesh.name
        if not self.armature:
            armature_data = bpy.data.armatures.new(armature_name + "_bones")
            armature_data.display_type = "OCTAHEDRAL"
            self.armature = bpy.data.objects.new(armature_name, armature_data)
            
            # Ensure Armature object is treated as Joint in UI
            self.armature.ls3d_frame_type_override = 10
            
            self.armature.show_in_front = True
            bpy.context.collection.objects.link(self.armature)
            bpy.context.view_layer.objects.active = self.armature
            bpy.ops.object.mode_set(mode="EDIT")
            base_bone = self.armature.data.edit_bones.new(armature_name)
         
            base_bone.head = Vector((0, -0.25, 0))
            base_bone.tail = Vector((0, 0, 0))
         
            self.base_bone_name = base_bone.name
            bpy.ops.object.mode_set(mode="OBJECT")
        mesh.name = armature_name
        self.armature.name = armature_name + "_armature"
        self.armature.parent = mesh
        vertex_groups = []
        bone_to_parent = {}
        for lod_id in range(num_lods):
            num_bones = struct.unpack("<B", f.read(1))[0]
            num_non_weighted_verts = struct.unpack("<I", f.read(4))[0]
            min_bounds = struct.unpack("<3f", f.read(12))
            max_bounds = struct.unpack("<3f", f.read(12))
            lod_vertex_groups = []
            sequential_bone_id = 0
            for _ in range(num_bones):
                inverse_transform = struct.unpack("<16f", f.read(64))
                num_locked = struct.unpack("<I", f.read(4))[0]
                num_weighted = struct.unpack("<I", f.read(4))[0]
                file_bone_id = struct.unpack("<I", f.read(4))[0]
                bone_min = struct.unpack("<3f", f.read(12))
                bone_max = struct.unpack("<3f", f.read(12))
                weights = list(struct.unpack(f"<{num_weighted}f", f.read(4 * num_weighted)))
                bone_id = sequential_bone_id
                sequential_bone_id += 1
                parent_id = 0
                for _, _, pid, bid in self.joints:
                    if bid == file_bone_id:
                        parent_id = pid
                        break
                bone_to_parent[bone_id] = parent_id
                lod_vertex_groups.append((bone_id, num_locked, weights))
            vertex_groups.append(lod_vertex_groups)
        self.skinned_meshes.append((mesh, vertex_groups, bone_to_parent))
        return vertex_groups
    
    def deserialize_dummy(self, f, empty, pos, rot, scale):
        # 1. Read Raw Mafia Coordinates (X, Y, Z)
        min_raw = struct.unpack("<3f", f.read(12))
        max_raw = struct.unpack("<3f", f.read(12))
        
        # 2. Convert to Blender Coordinates (Swap Y and Z)
        # Mafia (X, Y, Z) -> Blender (X, Z, Y)
        b_min = [min_raw[0], min_raw[2], min_raw[1]]
        b_max = [max_raw[0], max_raw[2], max_raw[1]]
        
        # 3. Store in Custom Properties (The Source of Truth)
        # We use a standard list so it's editable in UI
        empty["bbox_min"] = b_min
        empty["bbox_max"] = b_max
        
        # 4. Set Visual Size (For user convenience only)
        # We calculate the largest dimension to set the Blender Empty size
        width = abs(b_max[0] - b_min[0])
        depth = abs(b_max[1] - b_min[1])
        height = abs(b_max[2] - b_min[2])
        
        empty.empty_display_type = "CUBE"
        # Blender's empty size is "Radius" (half-width), so we take max dim / 2
        empty.empty_display_size = max(width, depth, height) * 0.5
        empty.show_name = True
    def deserialize_target(self, f, empty, pos, rot, scale):
        unknown = struct.unpack("<H", f.read(2))[0]
        num_links = struct.unpack("<B", f.read(1))[0]
        link_ids = struct.unpack(
            f"<{num_links}H", f.read(2 * num_links)
        )
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        empty.show_name = True
        empty.location = pos
        empty.rotation_mode = "QUATERNION"
        empty.rotation_quaternion = (rot[0], rot[1], rot[3], rot[2])
        empty.scale = scale
        empty["link_ids"] = list(link_ids)
    def deserialize_morph(self, f, mesh, num_vertices_per_lod):
            num_targets = struct.unpack("<B", f.read(1))[0]
            if num_targets == 0:
                return
            num_channels = struct.unpack("<B", f.read(1))[0]
            num_lods = struct.unpack("<B", f.read(1))[0]
            if len(num_vertices_per_lod) != num_lods:
                num_lods = min(num_lods, len(num_vertices_per_lod))
            morph_data = []
            for lod_idx in range(num_lods):
                lod_data = []
                for channel_idx in range(num_channels):
                    num_morph_vertices = struct.unpack("<H", f.read(2))[0]
                    if num_morph_vertices == 0:
                        lod_data.append([])
                        continue
                    vertex_data = []
                    for vert_idx in range(num_morph_vertices):
                        targets = []
                        for target_idx in range(num_targets):
                            p = struct.unpack("<3f", f.read(12))
                            n = struct.unpack("<3f", f.read(12))
                            # Convert coordinate system (Swap Y and Z)
                            p = (p[0], p[2], p[1])
                            n = (n[0], n[2], n[1])
                            targets.append((p, n))
                        vertex_data.append(targets)
                    unknown = struct.unpack("<?", f.read(1))[0]
                    vertex_indices = []
                    if unknown:
                        vertex_indices = struct.unpack(
                            f"<{num_morph_vertices}H", f.read(2 * num_morph_vertices)
                        )
                    else:
                        vertex_indices = list(range(num_morph_vertices))
                    lod_data.append((vertex_data, vertex_indices))
                morph_data.append(lod_data)
                min_bounds = struct.unpack("<3f", f.read(12))
                max_bounds = struct.unpack("<3f", f.read(12))
                center = struct.unpack("<3f", f.read(12))
                dist = struct.unpack("<f", f.read(4))
            # Apply shape keys to mesh
            if not mesh.data.shape_keys:
                mesh.shape_key_add(name="Basis", from_mix=False)
            for lod_idx in range(num_lods):
                num_vertices = num_vertices_per_lod[lod_idx]
                if len(mesh.data.vertices) != num_vertices:
                    continue
                lod_data = morph_data[lod_idx]
                for channel_idx in range(num_channels):
                    if not lod_data[channel_idx]:
                        continue
                    vertex_data, vertex_indices = lod_data[channel_idx]
                    for target_idx in range(num_targets):
                        shape_key_name = (
                            f"Target_{target_idx}_LOD{lod_idx}_Channel{channel_idx}"
                        )
                        shape_key = mesh.shape_key_add(name=shape_key_name, from_mix=False)
                        for morph_idx, vert_idx in enumerate(vertex_indices):
                            if vert_idx >= num_vertices:
                                continue
                            target_pos, _ = vertex_data[morph_idx][target_idx]
                            shape_key.data[vert_idx].co = target_pos
    
    def apply_deferred_parenting(self):
        # 1. Establish Hierarchy
        for frame_index, parent_id in self.parenting_info:
            if frame_index not in self.frames_map or parent_id not in self.frames_map:
                continue
            if frame_index == parent_id: 
                continue

            child_obj = self.frames_map[frame_index]
            parent_entry = self.frames_map[parent_id]
            parent_type = self.frame_types.get(parent_id, 0)

            if child_obj is None or isinstance(child_obj, str):
                continue

            # Bone Parenting
            if parent_type == FRAME_JOINT:
                if self.armature:
                    parent_bone_name = self.bones_map.get(parent_id)
                    if parent_bone_name and parent_bone_name in self.armature.data.bones:
                        self.parent_to_bone(child_obj, parent_bone_name)
            
            # Object Parenting
            elif not isinstance(parent_entry, str):
                # Standard Blender parenting tries to keep World Transform.
                child_obj.parent = parent_entry
                
                # CRITICAL: We reset the parent inverse.
                # This makes 'matrix_basis' (Local Transform) act exactly like the 
                # Transform Matrix stored in the 4DS file (Child relative to Parent).
                child_obj.matrix_parent_inverse = parent_entry.matrix_world.inverted()

        # 2. Apply Transforms
        # Now that hierarchy is linked and inverses are set, applying the raw matrix
        # puts the origin exactly where specified in the file relative to the parent.
        for fid, mat in self.frame_matrices.items():
            if fid in self.frames_map:
                obj = self.frames_map[fid]
                if not isinstance(obj, str) and obj is not None:
                    obj.matrix_basis = mat

    def deserialize_frame(self, f, materials, frames):
        # 1. READ HEADER
        raw_type = f.read(1)
        if not raw_type: return False
        frame_type = struct.unpack("<B", raw_type)[0]
        
        visual_type = 0
        visual_flags = (0, 0)
        
        if frame_type == 1: 
            visual_type = struct.unpack("<B", f.read(1))[0]
            visual_flags = struct.unpack("<2B", f.read(2))
            
        parent_id = struct.unpack("<H", f.read(2))[0]
        
        # 2. READ TRANSFORM (Mafia Space: X, Z, Y)
        # Position
        pos_raw = struct.unpack("<3f", f.read(12))
        # Scale
        scl_raw = struct.unpack("<3f", f.read(12))
        # Rotation (Quat)
        rot_raw = struct.unpack("<4f", f.read(16)) 
        
        # 3. CONVERT TO BLENDER LOCAL SPACE
        # Pos: (x, z, y) -> (x, y, z)
        pos = Vector((pos_raw[0], pos_raw[2], pos_raw[1]))
        
        # Scale: (x, z, y) -> (x, y, z)
        scl = Vector((scl_raw[0], scl_raw[2], scl_raw[1]))
        
        # Rot: (w, x, z, y) -> (w, x, y, z)
        # 4DS is W, X, Y, Z (but Y/Z swapped). Blender is W, X, Y, Z.
        rot_quat = Quaternion((rot_raw[0], rot_raw[1], rot_raw[3], rot_raw[2]))
        
        # Construct the Matrix to apply later
        local_matrix = Matrix.Translation(pos) @ rot_quat.to_matrix().to_4x4() @ Matrix.Diagonal(scl).to_4x4()
        self.frame_matrices[self.frame_index] = local_matrix
        
        # 4. READ PROPERTIES
        culling_flags = int(struct.unpack("<B", f.read(1))[0])
        name = self.read_string(f)
        user_props = self.read_string(f)
        
        self.frame_types[self.frame_index] = frame_type
        if parent_id > 0:
            self.parenting_info.append((self.frame_index, parent_id))
        
        mesh = None
        empty = None
        
        # 5. CREATE OBJECTS (Using exact names)
        if frame_type == 1: # FRAME_VISUAL
            mesh_data = bpy.data.meshes.new(name)
            mesh = bpy.data.objects.new(name, mesh_data)
            bpy.context.collection.objects.link(mesh)
            mesh.visual_type = str(visual_type)
            frames.append(mesh)
            self.frames_map[self.frame_index] = mesh
            self.frame_index += 1
            
            inst_id, v_per_lod = self.deserialize_object(f, materials, mesh, mesh_data, culling_flags)
            
            if visual_type == 4: # VISUAL_BILLBOARD
                if inst_id == 0: self.deserialize_billboard(f, mesh)
            elif inst_id == 0:
                if visual_type == 2: # VISUAL_SINGLEMESH
                    self.deserialize_singlemesh(f, len(v_per_lod), mesh)
                    self.bones_map[self.frame_index-1] = self.base_bone_name
                if visual_type in (3, 5): 
                    self.deserialize_morph(f, mesh, v_per_lod)

        elif frame_type == 5: # FRAME_SECTOR
            mesh = bpy.data.objects.new(name, bpy.data.meshes.new(name))
            bpy.context.collection.objects.link(mesh)
            frames.append(mesh); self.frames_map[self.frame_index] = mesh; self.frame_index += 1
            self.deserialize_sector(f, mesh)

        elif frame_type in (6, 7): # FRAME_DUMMY, FRAME_TARGET
            empty = bpy.data.objects.new(name, None)
            bpy.context.collection.objects.link(empty)
            frames.append(empty); self.frames_map[self.frame_index] = empty; self.frame_index += 1
            if frame_type == 6: self.deserialize_dummy(f, empty, pos, rot_quat, scl)
            else: self.deserialize_target(f, empty, pos, rot_quat, scl)
            
        elif frame_type == 12: # FRAME_OCCLUDER
            mesh = bpy.data.objects.new(name, bpy.data.meshes.new(name))
            bpy.context.collection.objects.link(mesh)
            frames.append(mesh); self.frames_map[self.frame_index] = mesh; self.frame_index += 1
            self.deserialize_occluder(f, mesh, pos, rot_quat, scl)
            
        elif frame_type == 10: # FRAME_JOINT
            f.read(64) 
            bone_id = struct.unpack("<I", f.read(4))[0]
            if self.armature:
                self.joints.append((name, local_matrix, parent_id, bone_id))
                self.bone_nodes[bone_id] = name
                self.bones_map[self.frame_index] = name
                self.frames_map[self.frame_index] = name
                self.frame_index += 1
        
        target_obj = mesh if mesh else empty
        if target_obj:
            # Note: We do NOT set matrix_basis here yet. 
            # We wait for hierarchy to be established in apply_deferred_parenting
            # to ensure the origin snaps correctly relative to parent.
            
            target_obj.ls3d_frame_type_override = frame_type
            target_obj.cull_flags = culling_flags
            target_obj.ls3d_user_props = user_props
            if frame_type == 1:
                target_obj.render_flags = visual_flags[0]
                target_obj.render_flags2 = visual_flags[1]
                
        return True
    
    def deserialize_material(self, f):
        mat = bpy.data.materials.new("material")
        
        # 1. Read Flags (Unsigned)
        flags = struct.unpack("<I", f.read(4))[0]
        
        # Convert to Signed for Blender Property
        signed_flags = flags if flags < 0x80000000 else flags - 0x100000000
        mat.ls3d_material_flags = signed_flags 

        # 2. Logic vars
        use_diffuse_tex = (flags & MTL_DIFFUSE_ENABLE) != 0
        use_color_key = (flags & MTL_ALPHA_COLORKEY) != 0
        
        # 3. Read Colors & Opacity
        mat.ls3d_ambient_color = struct.unpack("<3f", f.read(12))
        mat.ls3d_diffuse_color = struct.unpack("<3f", f.read(12))
        mat.ls3d_emission_color = struct.unpack("<3f", f.read(12))
        
        # Read Opacity to local variable
        raw_alpha = struct.unpack("<f", f.read(4))[0]

        metallic = 0.0
        diffuse_tex = ""
        env_tex = ""
        
        # 4. Textures
        # Environment
        if flags & MTL_ENV_ENABLE:
            metallic = struct.unpack("<f", f.read(4))[0]
            env_tex = self.read_string(f).lower()

        # Diffuse
        has_diffuse_string = False
        if use_diffuse_tex:
            has_diffuse_string = True
            diffuse_tex = self.read_string(f).lower()
            if len(diffuse_tex) > 0:
                mat.name = diffuse_tex

        # Alpha
        has_alpha_string = False
        alpha_tex = ""
        if (flags & MTL_ALPHA_ENABLE) and (flags & MTL_ALPHATEX):
            has_alpha_string = True
            alpha_tex = self.read_string(f).lower()

        # 5. Padding Byte (CRITICAL FIX)
        # In v29, Env Map does NOT count towards the texture check for padding.
        # We only skip the byte if Diffuse AND Alpha strings are missing.
        if not has_diffuse_string and not has_alpha_string:
             f.read(1)

        # 6. Anim Data (Exclusive Logic: Elif)
        # Also requires Signed Conversion
        if flags & MTL_ALPHA_ANIMATED:
            raw_frames = struct.unpack("<I", f.read(4))[0]
            f.read(2)
            raw_period = struct.unpack("<I", f.read(4))[0]
            f.read(8)
            mat.ls3d_alpha_anim_frames = raw_frames if raw_frames < 0x80000000 else raw_frames - 0x100000000
            mat.ls3d_alpha_anim_period = raw_period if raw_period < 0x80000000 else raw_period - 0x100000000

        elif flags & MTL_DIFFUSE_ANIMATED:
            raw_frames = struct.unpack("<I", f.read(4))[0]
            f.read(2)
            raw_period = struct.unpack("<I", f.read(4))[0]
            f.read(8)
            mat.ls3d_diffuse_anim_frames = raw_frames if raw_frames < 0x80000000 else raw_frames - 0x100000000
            mat.ls3d_diffuse_anim_period = raw_period if raw_period < 0x80000000 else raw_period - 0x100000000

        # 7. Setup Nodes
        self.set_material_data(
            mat, diffuse_tex, alpha_tex, env_tex, mat.ls3d_emission_color, 
            raw_alpha, metallic, use_color_key
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

    def deserialize_object(self, f, materials, mesh, mesh_data, culling_flags):
        raw_id = f.read(2)
        if not raw_id: return -1, []
        instance_id = struct.unpack("<H", raw_id)[0]
        
        if instance_id > 0:
            return instance_id, []
            
        num_lods = struct.unpack("<B", f.read(1))[0]
        vertices_per_lod = []
        base_name = mesh.name
        
        for lod_idx in range(num_lods):
            clipping_range = struct.unpack("<f", f.read(4))[0]
            
            if lod_idx > 0:
                name = f"{base_name}_lod{lod_idx}"
                m_data = bpy.data.meshes.new(name)
                new_mesh = bpy.data.objects.new(name, m_data)
                new_mesh.parent = mesh
                new_mesh.matrix_local = Matrix.Identity(4) 
                new_mesh.hide_viewport = True 
                bpy.context.collection.objects.link(new_mesh)
                new_mesh.ls3d_lod_dist = clipping_range
                current_mesh = m_data
            else:
                mesh.ls3d_lod_dist = clipping_range
                current_mesh = mesh_data

            num_vertices = struct.unpack("<H", f.read(2))[0]
            vertices_per_lod.append(num_vertices)
            
            raw_pos, raw_norm, raw_uv = [], [], []
            for _ in range(num_vertices):
                d = struct.unpack("<3f3f2f", f.read(32))
                raw_pos.append((d[0], d[2], d[1]))
                raw_norm.append((d[3], d[5], d[4]))
                raw_uv.append((d[6], 1.0 - d[7]))

            bm = bmesh.new()
            bm_verts = [bm.verts.new(p) for p in raw_pos]
            bm.verts.ensure_lookup_table()
            
            num_face_groups = struct.unpack("<B", f.read(1))[0]
            for _ in range(num_face_groups):
                num_faces = struct.unpack("<H", f.read(2))[0]
                raw_faces = struct.unpack(f"<{num_faces*3}H", f.read(num_faces * 6))
                mat_idx = struct.unpack("<H", f.read(2))[0]
                
                slot_index = 0
                if mat_idx > 0 and (mat_idx - 1) < len(materials):
                    target_mat = materials[mat_idx - 1]
                    if target_mat.name in current_mesh.materials:
                        slot_index = current_mesh.materials.find(target_mat.name)
                    else:
                        current_mesh.materials.append(target_mat)
                        slot_index = len(current_mesh.materials) - 1
                
                for i in range(0, len(raw_faces), 3):
                    try:
                        face = bm.faces.new((bm_verts[raw_faces[i]], bm_verts[raw_faces[i+2]], bm_verts[raw_faces[i+1]]))
                        face.material_index = slot_index
                        face.smooth = True
                    except ValueError:
                        pass 

            bm.to_mesh(current_mesh)
            bm.free()
            
            # UVs and Normals
            if num_vertices > 0:
                uv_layer = current_mesh.uv_layers.new(name="UVMap")
                loop_normals = []
                for loop in current_mesh.loops:
                    uv_layer.data[loop.index].uv = raw_uv[loop.vertex_index]
                    loop_normals.append(raw_norm[loop.vertex_index])
                try: current_mesh.normals_split_custom_set(loop_normals)
                except: pass
        
        return 0, vertices_per_lod
    
    def deserialize_sector(self, f, mesh):
        # 1. Set Frame Type to SECTOR (5) explicitly
        # This ensures the UI recognizes it as a Sector and allows its children to be Portals
        mesh.ls3d_frame_type_override = 5 
        
        f1 = struct.unpack("<i", f.read(4))[0]
        f2 = struct.unpack("<i", f.read(4))[0]
        
        mesh.ls3d_sector_flags1 = f1
        mesh.ls3d_sector_flags2 = f2
        
        bm = bmesh.new()
        num_verts = struct.unpack("<I", f.read(4))[0]
        num_faces = struct.unpack("<I", f.read(4))[0]
        
        vertices = []
        for _ in range(num_verts):
            p = struct.unpack("<3f", f.read(12))
            # Swap Y/Z
            vertices.append(bm.verts.new((p[0], p[2], p[1])))
        bm.verts.ensure_lookup_table()
        
        for _ in range(num_faces):
            idxs = struct.unpack("<3H", f.read(6))
            try: 
                # Swap Winding
                bm.faces.new([vertices[idxs[0]], vertices[idxs[2]], vertices[idxs[1]]])
            except: pass
            
        bm.to_mesh(mesh.data)
        bm.free()
        
        min_b = struct.unpack("<3f", f.read(12)); max_b = struct.unpack("<3f", f.read(12))
        mesh.bbox_min = (min_b[0], min_b[2], min_b[1])
        mesh.bbox_max = (max_b[0], max_b[2], max_b[1])
        
        num_portals = struct.unpack("<B", f.read(1))[0]
        for i in range(num_portals):
            self.deserialize_portal(f, mesh, i)

        # --- WIREFRAME SETTINGS ---
        mesh.display_type = 'WIRE'
        mesh.show_all_edges = True

    def deserialize_portal(self, f, parent_sector, index):
        num_verts = struct.unpack("<B", f.read(1))[0]
        
        flags = struct.unpack("<I", f.read(4))[0]
        near_r = struct.unpack("<f", f.read(4))[0]
        far_r = struct.unpack("<f", f.read(4))[0]
        
        normal = struct.unpack("<3f", f.read(12))
        dotp = struct.unpack("<f", f.read(4))[0]
        
        verts = []
        for _ in range(num_verts):
            p = struct.unpack("<3f", f.read(12))
            verts.append((p[0], p[2], p[1]))
            
        # Create Object (1-based index)
        p_name = f"{parent_sector.name}_portal{index + 1}"
        p_mesh = bpy.data.meshes.new(p_name)
        p_obj = bpy.data.objects.new(p_name, p_mesh)
        p_obj.parent = parent_sector
        bpy.context.collection.objects.link(p_obj)
        
        # --- CRITICAL FIX: Set Frame Type to SECTOR (5) ---
        # The UI logic requires: Type=5 AND ParentType=5 AND Name="...portal..."
        p_obj.ls3d_frame_type_override = 5
        
        # --- WIREFRAME SETTINGS ---
        p_obj.display_type = 'WIRE'
        
        # Apply flags to property
        p_obj.ls3d_portal_flags = flags
        p_obj.ls3d_portal_near = near_r
        p_obj.ls3d_portal_far = far_r
        
        bm = bmesh.new()
        for v in verts: bm.verts.new(v)
        bm.verts.ensure_lookup_table()
        if len(bm.verts) >= 3: 
            try: bm.faces.new(bm.verts)
            except: pass
        bm.to_mesh(p_mesh)
        bm.free()

    def deserialize_occluder(self, f, mesh, pos, rot, scl):
        # 1. Read Counts (uint32 from Max4ds)
        # We read these first to know how much data to expect
        data_counts = f.read(8) # 2 * 4 bytes
        if len(data_counts) < 8:
            print(f"LS3D Error: Occluder '{mesh.name}' truncated at header.")
            return
            
        num_verts, num_faces = struct.unpack("<2I", data_counts)
        
        # 2. Setup BMesh
        bm = bmesh.new()
        
        # 3. Read Vertices
        # Max4ds: for vertId = 1 to tr.numVerts do setVert...
        # Each vertex is 3 floats (12 bytes)
        verts = []
        try:
            for _ in range(num_verts):
                # Read 12 bytes
                data = f.read(12)
                if len(data) < 12:
                    raise struct.error("Unexpected EOF reading vertices")
                    
                v = struct.unpack("<3f", data)
                
                # Convert Mafia (X, Z, Y) -> Blender (X, Y, Z)
                # Occluders are local space, so we just swap axes
                verts.append(bm.verts.new((v[0], v[2], v[1])))
                
        except struct.error:
            print(f"LS3D Error: Occluder '{mesh.name}' corrupted vertex data.")
            bm.free()
            return

        bm.verts.ensure_lookup_table()
        
        # 4. Read Faces
        # Max4ds: for faceId = 1 to tr.numFaces...
        # Each face is 3 unsigned shorts (6 bytes)
        try:
            for _ in range(num_faces):
                data = f.read(6)
                if len(data) < 6:
                    raise struct.error("Unexpected EOF reading faces")
                    
                idx = struct.unpack("<3H", data)
                
                # Check indices valid range
                if idx[0] < num_verts and idx[1] < num_verts and idx[2] < num_verts:
                    try:
                        # Swap Winding: (0, 1, 2) -> (0, 2, 1) for Blender
                        bm.faces.new((verts[idx[0]], verts[idx[2]], verts[idx[1]]))
                    except ValueError:
                        pass # Ignore duplicate faces
                        
        except struct.error:
            print(f"LS3D Error: Occluder '{mesh.name}' corrupted face data.")

        # 5. Finalize
        bm.to_mesh(mesh.data)
        bm.free()
        
        # Occluders are usually wireframe in editors
        mesh.display_type = 'WIRE'
        mesh.show_all_edges = True

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
        # 1. Props
        dmin = struct.unpack("<3f", f.read(12))
        dmax = struct.unpack("<3f", f.read(12))
        center = struct.unpack("<3f", f.read(12))
        radius = struct.unpack("<f", f.read(4))[0]
        
        # Matrix (16 floats)
        mat_floats = struct.unpack("<16f", f.read(64))
        
        # Color (3 floats)
        rgb = struct.unpack("<3f", f.read(12))
        obj.mirror_color = rgb
        
        dist = struct.unpack("<f", f.read(4))[0]
        obj.mirror_dist = dist
        
        # 2. Mirror Mesh
        # It has its own geometry block inside the mirror struct
        num_verts = struct.unpack("<I", f.read(4))[0]
        num_faces = struct.unpack("<I", f.read(4))[0]
        
        bm = bmesh.new()
        vertices = []
        for _ in range(num_verts):
            p = struct.unpack("<3f", f.read(12))
            vertices.append(bm.verts.new((p[0], p[2], p[1])))
        bm.verts.ensure_lookup_table()
        
        for _ in range(num_faces):
            idxs = struct.unpack("<3H", f.read(6))
            try: bm.faces.new([vertices[idxs[0]], vertices[idxs[2]], vertices[idxs[1]]])
            except: pass
            
        bm.to_mesh(obj.data)
        bm.free()
    
class Export4DS(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.4ds"
    bl_label = "Export 4DS"
    filename_ext = ".4ds"
    filter_glob = StringProperty(default="*.4ds", options={"HIDDEN"})
    
    def validate_geometry(self, objects):
        """
        Validates geometry constraints:
        1. Sectors (Type 5, no portal name): Must be a Convex Volume (4+ faces).
        2. Portals (Type 5, portal name): Must be Planar, Convex, <= 32 verts.
        3. Occluders (Type 12): Must be Convex.
        """
        CONVEX_TOLERANCE = 0.01 

        for obj in objects:
            if obj.type != 'MESH':
                continue

            frame_type_str = getattr(obj, "ls3d_frame_type", '1')
            
            # Detect Portal by name pattern (Standard LS3D convention)
            # User Rule: Child of Sector + Type Sector + Suffix _portal<number>
            is_portal_name = bool(re.search(r"_portal\d+$", obj.name, re.IGNORECASE))
            
            # --- SECTOR (5) & OCCLUDER (12) CHECKS ---
            # We treat it as a Sector/Volume ONLY if it is NOT named like a portal.
            if frame_type_str in ('5', '12') and not is_portal_name:
                bm = bmesh.new()
                bm.from_mesh(obj.data)
                
                # Basic cleanup
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
                bmesh.ops.triangulate(bm, faces=bm.faces)
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

                # Sector Volume Check: Must have at least 4 faces to be a volume
                # We skip this check for Occluders (12) as they can sometimes be single planes (walls)
                if len(bm.faces) < 4 and frame_type_str == '5':
                    self.report({'ERROR'}, f"Export Stopped: Sector '{obj.name}' is not a volume (too few faces).\nIf this is a portal, ensure it is named ending in '_portal<number>'.")
                    bm.free()
                    return False

                # CONVEXITY CHECK (Plane Test)
                is_convex = True
                failure_reason = ""
                
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

                for face in bm.faces:
                    plane_co = face.calc_center_median()
                    plane_no = face.normal
                    
                    for v in bm.verts:
                        # Vector from plane to vertex
                        diff = v.co - plane_co
                        dist = diff.dot(plane_no)
                        
                        # Positive distance means vertex is "in front" of the face -> Concave
                        if dist > CONVEX_TOLERANCE:
                            is_convex = False
                            failure_reason = f"Concave geometry detected."
                            break
                    if not is_convex: break
                
                bm.free()

                if not is_convex:
                    self.report({'ERROR'}, f"Export Stopped: '{obj.name}' is NOT Convex.\nReason: {failure_reason}\nLS3D Engine requires Sectors and Occluders to be perfectly convex.")
                    return False

            # --- PORTAL CHECKS ---
            # Identify if it acts as a portal
            is_valid_portal = False
            if is_portal_name:
                if frame_type_str == '5': is_valid_portal = True
                if obj.parent and getattr(obj.parent, "ls3d_frame_type", '1') == '5': is_valid_portal = True
            
            if is_valid_portal:
                # 1. Planarity Check (Before dissolving)
                bm_p = bmesh.new()
                bm_p.from_mesh(obj.data)
                if len(bm_p.faces) > 0:
                    bm_p.faces.ensure_lookup_table()
                    ref_n = bm_p.faces[0].normal
                    ref_c = bm_p.faces[0].calc_center_median()
                    for v in bm_p.verts:
                        if abs((v.co - ref_c).dot(ref_n)) > 0.05:
                            self.report({'ERROR'}, f"Export Stopped: Portal '{obj.name}' is not flat."); bm_p.free(); return False
                
                # 2. N-Gon Vertex Count Check
                # Dissolve internal edges to find true perimeter count
                # bmesh.ops.remove_doubles(bm_p, verts=bm_p.verts, dist=0.001)
                bmesh.ops.dissolve_faces(bm_p, faces=bm_p.faces)
                
                # Count verts on the resulting face(s)
                bm_p.verts.ensure_lookup_table()
                unique_count = len(bm_p.verts)
                
                if unique_count > 8:
                    self.report({'ERROR'}, f"Export Stopped: Portal '{obj.name}' has {unique_count} vertices (Limit 8)."); bm_p.free(); return False
                if unique_count < 3:
                    self.report({'ERROR'}, f"Export Stopped: Portal '{obj.name}' has too few vertices."); bm_p.free(); return False
                
                bm_p.free()


        return True
    
    def execute(self, context):
        # Use selected objects if any, otherwise all objects in scene
        objects = context.selected_objects if context.selected_objects else context.scene.objects
        
        # Apply all transforms
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # 1. Validation
        if not self.validate_geometry(objects): 
            return {'CANCELLED'}
            
        # 2. Export
        exporter = The4DSExporter(self.filepath, objects)
        exporter.serialize_file()
        return {"FINISHED"}
    
class Import4DS(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.4ds"
    bl_label = "Import 4DS"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".4ds"
    filter_glob = StringProperty(default="*.4ds", options={"HIDDEN"})

    def execute(self, context):
        # 1. Define the Popup Draw Function
        def draw_loading_popup(self, context):
            layout = self.layout
            layout.label(text="LS3D Import Started...", icon='INFO')
            layout.separator()
            layout.label(text="Please wait while the model loads.")
            layout.label(text="Check System Console for detailed progress.")
            layout.label(text="(Window > Toggle System Console)")

        # 2. Spawn the Popup at Cursor
        context.window_manager.popup_menu(draw_loading_popup, title="Importing...", icon='TIME')

        # 3. Force UI Update (Hack to make the popup appear before the script freezes the UI)
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)

        # 4. Run the Actual Import
        importer = The4DSImporter(self.filepath)
        importer.import_file()
        
        return {"FINISHED"}
    
def menu_func_import(self, context):
    self.layout.operator(Import4DS.bl_idname, text="4DS Model File (.4ds)")

def menu_func_export(self, context):
    self.layout.operator(Export4DS.bl_idname, text="4DS Model File (.4ds)")

# --- PROPERTY HELPER FUNCTIONS ---
# These must exist before register() is called

# --- PROPERTY HELPER FUNCTIONS ---

def get_flag_bit(self, prop_name, bit_index):
    """Returns True if the specific bit is set (Handles negative integers correctly)."""
    value = getattr(self, prop_name, 0)
    return (value & (1 << bit_index)) != 0

def set_flag_bit(self, value, prop_name, bit_index):
    """
    Sets a bit safely for Blender's Signed 32-bit IntProperty.
    Prevents clamping when setting the 32nd bit (Additive).
    """
    # 1. Get current value as Unsigned 32-bit (Masking handles the negative sign)
    current_signed = getattr(self, prop_name, 0)
    current_unsigned = current_signed & 0xFFFFFFFF
    
    mask = 1 << bit_index

    # 2. Perform Bitwise Operation in Unsigned Space
    if value:
        new_unsigned = current_unsigned | mask
    else:
        new_unsigned = current_unsigned & ~mask

    # 3. Convert back to Signed 32-bit for Blender storage
    # If value is >= 2147483648 (0x80000000), it must become negative.
    if new_unsigned >= 0x80000000:
        new_signed = new_unsigned - 0x100000000
    else:
        new_signed = new_unsigned

    setattr(self, prop_name, int(new_signed))

def make_getter(prop_name, bit_index):
    return lambda self: get_flag_bit(self, prop_name, bit_index)

def make_setter(prop_name, bit_index):
    return lambda self, value: set_flag_bit(self, value, prop_name, bit_index)

# --- STRING PROPERTY HELPERS (For Raw Int Display) ---

def get_mat_flags_unsigned(self):
    """Converts the internal signed integer to a string representing the unsigned value."""
    val = self.ls3d_material_flags & 0xFFFFFFFF
    return str(val)

def set_mat_flags_unsigned(self, value):
    """Converts user input string back to signed integer for storage."""
    try:
        val = int(value, 0) # Supports '123' or '0xABC'
        val = val & 0xFFFFFFFF # Ensure 32-bit
        
        # Convert to signed
        signed_val = val if val < 0x80000000 else val - 0x100000000
        self.ls3d_material_flags = signed_val
    except ValueError:
        pass
    
    # --- SECTOR FLAG UI HELPERS ---

def get_sector_flags1_unsigned(self):
    """Converts internal signed int to unsigned string for UI."""
    val = self.ls3d_sector_flags1 & 0xFFFFFFFF
    return str(val)

def set_sector_flags1_unsigned(self, value):
    """Converts UI string back to signed int for storage."""
    try:
        val = int(value, 0)
        val = val & 0xFFFFFFFF
        # Convert to signed 32-bit
        signed_val = val if val < 0x80000000 else val - 0x100000000
        self.ls3d_sector_flags1 = signed_val
    except ValueError:
        pass

def get_sector_flags2_unsigned(self):
    val = self.ls3d_sector_flags2 & 0xFFFFFFFF
    return str(val)

def set_sector_flags2_unsigned(self, value):
    try:
        val = int(value, 0)
        val = val & 0xFFFFFFFF
        signed_val = val if val < 0x80000000 else val - 0x100000000
        self.ls3d_sector_flags2 = signed_val
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
def get_frame_type_callback(self):
    """Calculates the Enum Index based on the object type."""
    stored_val = self.ls3d_frame_type_override
    target_id = '6' # Default to Dummy
    
    if stored_val != 0:
        target_id = str(stored_val)
    else:
        # Auto-Detect based on Blender Object
        if self.type == 'MESH':
            if "sector" in self.name.lower(): target_id = '5'
            elif "portal" in self.name.lower(): target_id = '1'
            elif self.display_type == 'WIRE': target_id = '12'
            else: target_id = '1'
        # Removed detection for LIGHT, CAMERA, SPEAKER
        elif self.type == 'EMPTY':
            if self.empty_display_type == 'PLAIN_AXES': target_id = '7'
            elif self.empty_display_type == 'SINGLE_ARROW': target_id = '9'
            else: target_id = '6'
        elif self.type == 'ARMATURE': 
            target_id = '10' # FRAME_JOINT
        
    # Find the index of this ID in the items list
    for i, item in enumerate(LS3D_FRAME_ITEMS):
        if item[0] == target_id:
            return i
    return 0

def set_frame_type_callback(self, value):
    """Saves the selected Enum value and updates viewport display immediately."""
    if 0 <= value < len(LS3D_FRAME_ITEMS):
        selected_id = int(LS3D_FRAME_ITEMS[value][0])
        self.ls3d_frame_type_override = selected_id
        
        # --- VISUAL FEEDBACK LOGIC ---
        
        # Case A: Wireframe Objects (Sector=5, Occluder=12)
        if selected_id in (5, 12): 
            self.display_type = 'WIRE'      # Set viewport draw mode to Wire
            self.show_all_edges = True      # CRITICAL: Show internal triangulation lines even on flat faces
            self.show_wire = True           # Force wireframe overlay on
            
        # Case B: Standard Visual (1)
        elif selected_id == 1: 
            self.display_type = 'TEXTURED'  # Standard solid view
            self.show_all_edges = False     # Optimize display (hide internal diagonals)
            self.show_wire = False
            
        # Case C: Dummies/Helpers (6, 7, 9, 10)
        # Note: If it's a Mesh acting as a dummy, we usually want bounds or wire
        elif self.type == 'MESH':
             if selected_id != 1:
                 self.display_type = 'WIRE'

# --- REGISTRATION ---

def register():
    # Classes
    bpy.utils.register_class(LS3D_AddonPreferences)
    bpy.utils.register_class(LS3D_OT_AddEnvSetup)
    bpy.utils.register_class(LS3D_OT_AddNode)
    bpy.utils.register_class(The4DSPanelMaterial)
    bpy.utils.register_class(The4DSPanel)
    bpy.utils.register_class(Import4DS)
    bpy.utils.register_class(Export4DS)

    # --- SCENE ---
    bpy.types.Scene.ls3d_is_animated = BoolProperty(name="Is Animated", default=False)

    # --- OBJECT PROPERTIES ---
    bpy.types.Object.ls3d_frame_type_override = IntProperty(default=0)
    bpy.types.Object.ls3d_frame_type = EnumProperty(name="Frame Type", items=LS3D_FRAME_ITEMS, get=get_frame_type_callback, set=set_frame_type_callback)
    
    bpy.types.Object.visual_type = EnumProperty(
        name="Mesh Type", 
        items=(
            ('0', "Standard", "Standard Static Mesh"), 
            ('1', "Lit Object", "Pre-lit Object"), 
            ('2', "Single Mesh", "Skinned Mesh"), 
            ('3', "Single Morph", "Car/Morph Mesh"), 
            ('4', "Billboard", "Sprite/Billboard"), 
            ('5', "Morph", "Character Morph"), 
            ('6', "Lens Flare", "Lens Flare Source"), 
            ('7', "Projector", "Light Projector"),
            ('8', "Mirror", "Reflection Plane"),
            ('9', "Emitor", "Particle Emitter")
        ), 
        default='0'
    )
    
    # --- OBJECT CULLING FLAGS ---
    bpy.types.Object.cull_flags = IntProperty(name="Culling Flags", default=0, min=0)
    bpy.types.Object.cf_node_visible = BoolProperty(name="Visible", get=make_getter("cull_flags", 0), set=make_setter("cull_flags", 0))
    bpy.types.Object.cf_node_cam_coll = BoolProperty(name="Camera Collision", get=make_getter("cull_flags", 1), set=make_setter("cull_flags", 1))
    bpy.types.Object.cf_node_collision = BoolProperty(name="Physics Collision", get=make_getter("cull_flags", 2), set=make_setter("cull_flags", 2))
    bpy.types.Object.cf_node_castshadow = BoolProperty(name="Cast Shadow", get=make_getter("cull_flags", 3), set=make_setter("cull_flags", 3))
    bpy.types.Object.cf_node_update = BoolProperty(name="Update/Movable", get=make_getter("cull_flags", 4), set=make_setter("cull_flags", 4))
    bpy.types.Object.cf_node_freeze = BoolProperty(name="Freeze/Static", get=make_getter("cull_flags", 5), set=make_setter("cull_flags", 5))
    bpy.types.Object.cf_node_hierarchy = BoolProperty(name="Hierarchy", get=make_getter("cull_flags", 6), set=make_setter("cull_flags", 6))
    
    # --- VISUAL RENDER FLAGS ---
    bpy.types.Object.render_flags = IntProperty(name="Render Flags 1", default=0, min=0)
    bpy.types.Object.render_flags2 = IntProperty(name="Render Flags 2", default=0, min=0)
    
    bpy.types.Object.rf1_cast_shadow = BoolProperty(name="Cast Shadow", get=make_getter("render_flags", 0), set=make_setter("render_flags", 0))
    bpy.types.Object.rf1_receive_shadow = BoolProperty(name="Receive Shadow", get=make_getter("render_flags", 1), set=make_setter("render_flags", 1))
    bpy.types.Object.rf1_draw_last = BoolProperty(name="Draw Last", get=make_getter("render_flags", 2), set=make_setter("render_flags", 2))
    bpy.types.Object.rf1_zbias = BoolProperty(name="Z-Bias", get=make_getter("render_flags", 3), set=make_setter("render_flags", 3))
    bpy.types.Object.rf1_bright = BoolProperty(name="Bright (Unlit)", get=make_getter("render_flags", 4), set=make_setter("render_flags", 4))
    
    bpy.types.Object.rf2_decal = BoolProperty(name="Decal", get=make_getter("render_flags2", 0), set=make_setter("render_flags2", 0))
    bpy.types.Object.rf2_stencil = BoolProperty(name="Stencil", get=make_getter("render_flags2", 1), set=make_setter("render_flags2", 1))
    bpy.types.Object.rf2_mirror = BoolProperty(name="Mirror", get=make_getter("render_flags2", 2), set=make_setter("render_flags2", 2))
    bpy.types.Object.rf2_fadeout = BoolProperty(name="Fade Out", get=make_getter("render_flags2", 3), set=make_setter("render_flags2", 3))
    bpy.types.Object.rf2_proj = BoolProperty(name="Projector", get=make_getter("render_flags2", 5), set=make_setter("render_flags2", 5))
    bpy.types.Object.rf2_nofog = BoolProperty(name="No Fog", get=make_getter("render_flags2", 7), set=make_setter("render_flags2", 7))

    # --- MATERIAL PROPERTIES ---
    bpy.types.Material.ls3d_ambient_color = FloatVectorProperty(subtype='COLOR', default=(0.5,0.5,0.5), name="Ambient")
    bpy.types.Material.ls3d_diffuse_color = FloatVectorProperty(subtype='COLOR', default=(1,1,1), name="Diffuse")
    bpy.types.Material.ls3d_emission_color = FloatVectorProperty(subtype='COLOR', default=(0,0,0), name="Emission")

    # Animations
    bpy.types.Material.ls3d_diffuse_anim_frames = IntProperty(name="Diff Frames", default=0)
    bpy.types.Material.ls3d_diffuse_anim_period = IntProperty(name="Diff Period", default=0)
    bpy.types.Material.ls3d_alpha_anim_frames = IntProperty(name="Alpha Frames", default=0)
    bpy.types.Material.ls3d_alpha_anim_period = IntProperty(name="Alpha Period", default=0)

    # --- MATERIAL FLAGS ---
    bpy.types.Material.ls3d_material_flags = IntProperty(name="Material Flags", default=0)
    bpy.types.Material.ls3d_material_flags_str = StringProperty(name="Raw Flags", description="Raw Unsigned Integer", get=get_mat_flags_unsigned, set=set_mat_flags_unsigned)

    # Boolean accessors
    bpy.types.Material.ls3d_flag_misc_unlit = BoolProperty(name="Unlit", description="Disable lighting calculations (0x1)", get=make_getter("ls3d_material_flags", 0), set=make_setter("ls3d_material_flags", 0))
    bpy.types.Material.ls3d_flag_env_overlay = BoolProperty(name="Env Overlay", get=make_getter("ls3d_material_flags", 8), set=make_setter("ls3d_material_flags", 8))
    bpy.types.Material.ls3d_flag_env_multiply = BoolProperty(name="Env Multiply", get=make_getter("ls3d_material_flags", 9), set=make_setter("ls3d_material_flags", 9))
    bpy.types.Material.ls3d_flag_env_additive = BoolProperty(name="Env Additive", get=make_getter("ls3d_material_flags", 10), set=make_setter("ls3d_material_flags", 10))
    bpy.types.Material.ls3d_flag_env_use_map = BoolProperty(name="Use Env Map", get=make_getter("ls3d_material_flags", 11), set=make_setter("ls3d_material_flags", 11))
    bpy.types.Material.ls3d_flag_env_projy = BoolProperty(name="Proj Y", get=make_getter("ls3d_material_flags", 12), set=make_setter("ls3d_material_flags", 12))
    bpy.types.Material.ls3d_flag_env_detaily = BoolProperty(name="Detail Y", get=make_getter("ls3d_material_flags", 13), set=make_setter("ls3d_material_flags", 13))
    bpy.types.Material.ls3d_flag_env_detailz = BoolProperty(name="Detail Z", get=make_getter("ls3d_material_flags", 14), set=make_setter("ls3d_material_flags", 14))
    
    bpy.types.Material.ls3d_flag_alpha_enable = BoolProperty(name="Alpha Enable", description="Enables alpha effect, if No Alpha Texture is specified, game looks for the Diffuse Texture Name that ends with + and uses it as Alpha Texture in LS3D Engine", get=make_getter("ls3d_material_flags", 15), set=make_setter("ls3d_material_flags", 15))
    bpy.types.Material.ls3d_flag_disable_u_tiling = BoolProperty(name="Disable U-Tile", get=make_getter("ls3d_material_flags", 16), set=make_setter("ls3d_material_flags", 16))
    bpy.types.Material.ls3d_flag_disable_v_tiling = BoolProperty(name="Disable V-Tile", get=make_getter("ls3d_material_flags", 17), set=make_setter("ls3d_material_flags", 17))
    
    bpy.types.Material.ls3d_flag_diffuse_enable = BoolProperty(name="Use Diffuse", get=make_getter("ls3d_material_flags", 18), set=make_setter("ls3d_material_flags", 18))
    bpy.types.Material.ls3d_flag_env_enable = BoolProperty(name="Env Enable", get=make_getter("ls3d_material_flags", 19), set=make_setter("ls3d_material_flags", 19))
    bpy.types.Material.ls3d_flag_diffuse_mipmap = BoolProperty(name="MipMap", get=make_getter("ls3d_material_flags", 23), set=make_setter("ls3d_material_flags", 23))
    
    bpy.types.Material.ls3d_flag_alpha_in_tex = BoolProperty(name="Alpha In Tex", get=make_getter("ls3d_material_flags", 24), set=make_setter("ls3d_material_flags", 24))
    bpy.types.Material.ls3d_flag_alpha_animated = BoolProperty(name="Anim Alpha", get=make_getter("ls3d_material_flags", 25), set=make_setter("ls3d_material_flags", 25))
    bpy.types.Material.ls3d_flag_diffuse_animated = BoolProperty(name="Anim Diffuse", get=make_getter("ls3d_material_flags", 26), set=make_setter("ls3d_material_flags", 26))
    bpy.types.Material.ls3d_flag_diffuse_colored = BoolProperty(name="Vertex Colors", get=make_getter("ls3d_material_flags", 27), set=make_setter("ls3d_material_flags", 27))
    bpy.types.Material.ls3d_flag_diffuse_doublesided = BoolProperty(name="Double Sided", get=make_getter("ls3d_material_flags", 28), set=make_setter("ls3d_material_flags", 28))
    bpy.types.Material.ls3d_flag_alpha_colorkey = BoolProperty(name="Color Key", get=make_getter("ls3d_material_flags", 29), set=make_setter("ls3d_material_flags", 29))
    bpy.types.Material.ls3d_flag_alphatex = BoolProperty(name="Alpha Texture", get=make_getter("ls3d_material_flags", 30), set=make_setter("ls3d_material_flags", 30))
    bpy.types.Material.ls3d_flag_alpha_additive = BoolProperty(name="Additive", get=make_getter("ls3d_material_flags", 31), set=make_setter("ls3d_material_flags", 31))

    # Standard Props
    bpy.types.Object.ls3d_lod_dist = FloatProperty(name="LOD Dist", default=0.0)
    bpy.types.Object.ls3d_user_props = StringProperty(name="User Props")
    bpy.types.Object.rot_mode = EnumProperty(items=(('1','All',''),('2','Single','')), name="Rot Mode")
    bpy.types.Object.rot_axis = EnumProperty(items=(('1','X',''),('2','Z',''),('3','Y','')), name="Rot Axis")
    bpy.types.Object.mirror_color = FloatVectorProperty(name="Mirror Color")
    bpy.types.Object.mirror_dist = FloatProperty(name="Mirror Dist")
    bpy.types.Object.bbox_min = FloatVectorProperty(name="BBox Min")
    bpy.types.Object.bbox_max = FloatVectorProperty(name="BBox Max")
    
    # --- SECTOR PROPS (FIXED) ---
    # Internal Signed Storage with Limits
    bpy.types.Object.ls3d_sector_flags1 = IntProperty(default=0)
    bpy.types.Object.ls3d_sector_flags2 = IntProperty(default=0)
    
    # UI String Displays (Unsigned)
    bpy.types.Object.ls3d_sector_flags1_str = StringProperty(name="Raw Flags 1", description="Raw Unsigned Integer", get=get_sector_flags1_unsigned, set=set_sector_flags1_unsigned)
    bpy.types.Object.ls3d_sector_flags2_str = StringProperty(name="Raw Flags 2", description="Raw Unsigned Integer", get=get_sector_flags2_unsigned, set=set_sector_flags2_unsigned)

    # Boolean accessors for Sector Flags 1
    bpy.types.Object.sf_active = BoolProperty(name="Active", get=make_getter("ls3d_sector_flags1", 0), set=make_setter("ls3d_sector_flags1", 0))
    bpy.types.Object.sf_collision = BoolProperty(name="Collision", get=make_getter("ls3d_sector_flags1", 10), set=make_setter("ls3d_sector_flags1", 10))
    bpy.types.Object.sf_indoor = BoolProperty(name="Indoor", get=make_getter("ls3d_sector_flags1", 11), set=make_setter("ls3d_sector_flags1", 11))
    
    # Portal Props
    bpy.types.Object.ls3d_portal_flags = IntProperty()
    bpy.types.Object.ls3d_portal_near = FloatProperty()
    bpy.types.Object.ls3d_portal_far = FloatProperty()
    bpy.types.Object.pf_enabled = BoolProperty(name="Enabled", get=make_getter("ls3d_portal_flags", 2), set=make_setter("ls3d_portal_flags", 2))
    bpy.types.Object.pf_mirror = BoolProperty(name="Mirror", get=make_getter("ls3d_portal_flags", 3), set=make_setter("ls3d_portal_flags", 3))
    bpy.types.Object.pf_bit0 = BoolProperty(name="Bit 0", get=make_getter("ls3d_portal_flags", 0), set=make_setter("ls3d_portal_flags", 0))
    bpy.types.Object.pf_bit1 = BoolProperty(name="Bit 1", get=make_getter("ls3d_portal_flags", 1), set=make_setter("ls3d_portal_flags", 1))

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
    
    del bpy.types.Scene.ls3d_is_animated
    
    # Object Props
    del bpy.types.Object.ls3d_frame_type
    del bpy.types.Object.ls3d_frame_type_override
    del bpy.types.Object.visual_type
    del bpy.types.Object.cull_flags
    del bpy.types.Object.cf_node_visible
    del bpy.types.Object.cf_node_collision
    del bpy.types.Object.cf_node_castshadow
    del bpy.types.Object.cf_node_update
    del bpy.types.Object.cf_node_freeze
    del bpy.types.Object.cf_node_visible
    del bpy.types.Object.cf_node_cam_coll
    del bpy.types.Object.cf_node_collision
    del bpy.types.Object.cf_node_castshadow
    del bpy.types.Object.cf_node_update
    del bpy.types.Object.cf_node_freeze
    del bpy.types.Object.cf_node_hierarchy
    del bpy.types.Object.render_flags
    del bpy.types.Object.render_flags2
    del bpy.types.Object.rf1_cast_shadow
    del bpy.types.Object.rf1_receive_shadow
    del bpy.types.Object.rf1_draw_last
    del bpy.types.Object.rf1_zbias
    del bpy.types.Object.rf1_bright
    del bpy.types.Object.rf2_decal
    del bpy.types.Object.rf2_stencil
    del bpy.types.Object.rf2_mirror
    del bpy.types.Object.rf2_fadeout
    del bpy.types.Object.rf2_proj
    del bpy.types.Object.rf2_nofog
    del bpy.types.Object.ls3d_lod_dist
    del bpy.types.Object.ls3d_user_props
    del bpy.types.Object.ls3d_sector_flags1
    del bpy.types.Object.ls3d_sector_flags2
    del bpy.types.Object.ls3d_sector_flags1_str
    del bpy.types.Object.ls3d_sector_flags2_str
    del bpy.types.Object.sf_active
    del bpy.types.Object.sf_collision
    del bpy.types.Object.sf_indoor
    
    del bpy.types.Object.ls3d_portal_flags
    del bpy.types.Object.ls3d_portal_near
    del bpy.types.Object.ls3d_portal_far
    del bpy.types.Object.pf_enabled
    del bpy.types.Object.pf_mirror
    del bpy.types.Object.pf_bit0
    del bpy.types.Object.pf_bit1
    
    del bpy.types.Object.rot_mode
    del bpy.types.Object.rot_axis
    del bpy.types.Object.mirror_color
    del bpy.types.Object.mirror_dist
    del bpy.types.Object.bbox_min
    del bpy.types.Object.bbox_max

    # Material Values
    del bpy.types.Material.ls3d_ambient_color
    del bpy.types.Material.ls3d_diffuse_color
    del bpy.types.Material.ls3d_emission_color
    
    # New Split Props
    del bpy.types.Material.ls3d_diffuse_anim_frames
    del bpy.types.Material.ls3d_diffuse_anim_period
    del bpy.types.Material.ls3d_alpha_anim_frames
    del bpy.types.Material.ls3d_alpha_anim_period

    # Material Flags
    del bpy.types.Material.ls3d_material_flags
    del bpy.types.Material.ls3d_material_flags_str
    del bpy.types.Material.ls3d_flag_misc_unlit
    del bpy.types.Material.ls3d_flag_env_overlay
    del bpy.types.Material.ls3d_flag_env_multiply
    del bpy.types.Material.ls3d_flag_env_additive
    del bpy.types.Material.ls3d_flag_envtex
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

    bpy.utils.unregister_class(LS3D_OT_AddEnvSetup)
    bpy.utils.unregister_class(LS3D_OT_AddNode)
    bpy.utils.unregister_class(The4DSPanelMaterial)
    bpy.utils.unregister_class(The4DSPanel)
    bpy.utils.unregister_class(Import4DS)
    bpy.utils.unregister_class(Export4DS)

if __name__ == "__main__":
    register()

