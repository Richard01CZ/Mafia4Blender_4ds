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
    "version": (0, 1, 0, 'preview' ),
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
FRAME_LIGHT = 2         # Possibly HD2?             UNSUPPORTED
FRAME_CAMERA = 3        # Possibly HD2?             UNSUPPORTED
FRAME_SOUND = 4         # Possibly HD2?             UNSUPPORTED  
FRAME_SECTOR = 5        # 3D Object Wireframe       COMPLETE                    Make it so sector deosn't require flipping normals (currently sector requires to have it's faces facing inside)
FRAME_DUMMY = 6         # Empty (Cube)              COMPLETE                    Dummies are mostlikely displayed incorrectly for vehicles
FRAME_TARGET = 7        # Empty (Plain Axis)        TO DO       PART OF CHARACTER MODELS
FRAME_USER = 8          # HD2                       UNSUPPORTED
FRAME_MODEL = 9         # Empty (Arrows)            UNSUPPORTED
FRAME_JOINT = 10        # Armature/Bones            TO DO       PART OF CHARACTER MODELS
FRAME_VOLUME = 11       # HD2                       UNSUPPORTED
FRAME_OCCLUDER = 12     # 3D Object Wireframe       COMPLETE                    Occluder isn't correctly parsed/imported by Mafcapone, software update required to fix this. Occluders in seperate blender collection are recommended
FRAME_SCENE = 13        # HD2                       UNSUPPORTED
FRAME_AREA = 14         # HD2                       UNSUPPORTED
FRAME_LANDSCAPE = 15    # HD2                       UNSUPPORTED

# Add an option to show or hide the raw int values in 4ds side panels
# Check if bones and weights are being imported and exported correctly using max4dstools or mafia_5ds on github as a reference
# Check how 6DS files work to see if we can add custom Shadow Models
# make sure we also export shape keys correctly

# Map vehicle dummies and create N panel with all dummy types for a specific thing of the vehicle.

# Visual Types
VISUAL_OBJECT = 0           # COMPLETE ?
VISUAL_LITOBJECT = 1        # TO DO         Only writes the byte that is different, otherwise same as VISUAL_OBJECT
VISUAL_SINGLEMESH = 2       # TO DO         PART OF CHARACTER MODELS
VISUAL_SINGLEMORPH = 3      # TO DO         PART OF CHARACTER MODELS
VISUAL_BILLBOARD = 4        # COMPLETE
VISUAL_MORPH = 5            # TO DO         PART OF CHARACTER MODELS
VISUAL_LENSFLARE = 6        # COMPLETE
VISUAL_PROJECTOR = 7        # UNSUPPORTED
VISUAL_MIRROR = 8           # COMPLETE
VISUAL_EMITOR = 9           # UNSUPPORTED

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
RF_UNKNOWN7         = 0x40  # 64
RF_UNKNOWN8         = 0x80  # 128

# --- VISUAL LOGIC FLAGS (Byte 2) ---
LF_DECAL                        = 0x01  # 1 Object is a decal (Poster, picture on a wall). helps with z-fighting on flat surfaces by drawing the object above the surface.
LF_RECIEVE_DYNAMIC_SHADOW       = 0x02  # 2 Objects can recieve dynamic shadows (eg. from player or vehicle)
LF_UNKNOWN3                     = 0x04  # 4 Mirror? Transparency sorting priority ?? m_palmop01.4ds, la_N_flag01.4ds, b_art16.4ds, m_AF3_kob03.4ds                          [Description may apply to HD2 only]
LF_UNKNOWN4                     = 0x08  # 8 Fade out?
LF_UNKNOWN5                     = 0x10  # 16 Used for equipment (bagpacks, hats, weapons)                                                                                   [Description may apply to HD2 only]
LF_RECIEVE_PROJECTION           = 0x20  # 32 Objects can recieve projection textures (eg. Car headlights, bullet hole decals)
LF_UNKNOWN7                     = 0x40  # 64 Sound Occluder?
LF_NO_FOG                       = 0x80  # 128 Object isn't affected by the fog

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
PF_MIRROR               = 0x00000008 # Nejsem si jistej jestli to dela mirror, jeste jsem se k mirror nedostal

class LS3D_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    textures_path: StringProperty(name="Path to Textures", description='Path to the textures "maps" folder. This path is used by the importer.', subtype='DIR_PATH') # type: ignore / drž píču už, funguješ

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
        layout = self.layout
        obj = context.object

        # =====================================================
        # MODEL SETTINGS
        # =====================================================
        box = layout.box()
        box.label(text="Model Settings", icon='SCENE_DATA')
        box.prop(context.scene, "ls3d_animated_object_count")

        if not obj:
            return

        layout.separator()

        # =====================================================
        # FRAME TYPE
        # =====================================================
        layout.prop(obj, "ls3d_frame_type", text="Frame Type")

        try:
            frame_type = int(obj.ls3d_frame_type)
        except:
            return

        # =====================================================
        # PORTAL DETECTION (STRICT)
        # =====================================================
        is_portal = (
            obj.type == 'MESH'
            and frame_type == FRAME_SECTOR
            and obj.parent
            and int(getattr(obj.parent, "ls3d_frame_type", '0')) == FRAME_SECTOR
            and re.search(r"_portal\d+$", obj.name, re.IGNORECASE)
        )

        # =====================================================
        # VISUAL FRAME
        # =====================================================
        if frame_type == FRAME_VISUAL:

            layout.prop(obj, "visual_type", text="Visual Type")

            try:
                visual_type = int(obj.visual_type)
            except:
                visual_type = 0

            # --------------------------------------------
            # LENS FLARE (EMPTY ONLY)
            # --------------------------------------------
            if visual_type == VISUAL_LENSFLARE and obj.type == 'EMPTY':

                box = layout.box()
                box.label(text="Lens Flare", icon='LIGHT')
                box.prop(obj, "ls3d_glow_position", text="Screen Position")
                box.prop(obj, "ls3d_glow_material", text="Material")

            # --------------------------------------------
            # MIRROR (MESH ONLY)
            # --------------------------------------------
            elif visual_type == VISUAL_MIRROR and obj.type == 'MESH':

                box = layout.box()
                box.label(text="Mirror", icon='MOD_MIRROR')
                box.prop(obj, "ls3d_mirror_color", text="Color")
                box.prop(obj, "ls3d_mirror_range", text="Active Range")

            # --------------------------------------------
            # BILLBOARD
            # --------------------------------------------
            elif visual_type == VISUAL_BILLBOARD:

                box = layout.box()
                box.label(text="Billboard", icon='IMAGE_PLANE')
                box.prop(obj, "rot_mode", text="Rotation Mode")
                if obj.rot_mode == '2':
                    box.prop(obj, "rot_axis", text="Rotation Axis")

            # --------------------------------------------
            # STANDARD VISUAL MESH
            # --------------------------------------------
            if obj.type == 'MESH' and visual_type != VISUAL_LENSFLARE:

                box = layout.box()
                box.label(text="Rendering Flags", icon='RESTRICT_RENDER_OFF')
                box.prop(obj, "render_flags", text="Raw Int")

                grid = box.grid_flow(columns=2, align=True)
                grid.prop(obj, "rf1_unknown1")
                grid.prop(obj, "rf1_unknown2")
                grid.prop(obj, "rf1_unknown3")
                grid.prop(obj, "rf1_unknown4")
                grid.prop(obj, "rf1_unknown5")
                grid.prop(obj, "rf1_unknown6")
                grid.prop(obj, "rf1_unknown7")
                grid.prop(obj, "rf1_unknown8")

                box = layout.box()
                box.label(text="Logic Flags", icon='MODIFIER')
                box.prop(obj, "render_flags2", text="Raw Int")

                grid = box.grid_flow(columns=2, align=True)
                grid.prop(obj, "rf2_zbias")
                grid.prop(obj, "rf2_recieve_dynamic_shadow")
                grid.prop(obj, "rf2_unknown3")
                grid.prop(obj, "rf2_unknown4")
                grid.prop(obj, "rf2_unknown5")
                grid.prop(obj, "rf2_recieve_projection")
                grid.prop(obj, "rf2_unknown7")
                grid.prop(obj, "rf2_no_fog")

                box = layout.box()
                box.label(text="Level Of Detail", icon='MESH_DATA')
                box.prop(obj, "ls3d_lod_dist", text="Fade Distance")

        # =====================================================
        # SECTOR
        # =====================================================
        elif frame_type == FRAME_SECTOR and not is_portal:

            box = layout.box()
            box.label(text="Sector Flags", icon='SCENE_DATA')
            box.prop(obj, "ls3d_sector_flags1_str", text="Raw Flags 1")
            box.prop(obj, "ls3d_sector_flags2_str", text="Raw Flags 2")

            grid = box.grid_flow(columns=2, align=True)
            grid.prop(obj, "sf_enabled")
            grid.prop(obj, "sf_unknown7")
            grid.prop(obj, "sf_unknown8")

        # =====================================================
        # PORTAL
        # =====================================================
        elif is_portal:

            box = layout.box()
            box.label(text="Portal Config", icon='OUTLINER_OB_LIGHT')

            box.prop(obj, "ls3d_portal_flags", text="Raw Flags")

            row = box.row(align=True)
            row.prop(obj, "ls3d_portal_near", text="Near")
            row.prop(obj, "ls3d_portal_far", text="Far")

            grid = box.grid_flow(columns=2, align=True)
            grid.prop(obj, "pf_unknown1")
            grid.prop(obj, "pf_unknown2")
            grid.prop(obj, "pf_enabled")
            grid.prop(obj, "pf_mirror")

        # =====================================================
        # DUMMY
        # =====================================================
        elif frame_type == FRAME_DUMMY:

            box = layout.box()
            box.label(text="Dummy Bounding Box", icon='SHADING_BBOX')
            box.label(text="No editable properties")

            # if "bbox_min" in obj:
            #     box.prop(obj, '["bbox_min"]', text="Min")
            #     box.prop(obj, '["bbox_max"]', text="Max")
            # else:
            #     box.label(text="No BBox Data (Will Auto-Generate)", icon='ERROR')

        # =====================================================
        # OCCLUDER
        # =====================================================
        elif frame_type == FRAME_OCCLUDER:

            box = layout.box()
            box.label(text="Occluder", icon='MOD_BOOLEAN')
            box.label(text="No editable properties")

        # =====================================================
        # NODE CULLING (ALL FRAMES)
        # =====================================================
        box = layout.box()
        box.label(text="Node Culling Flags", icon='PROPERTIES')
        box.prop(obj, "cull_flags", text="Raw Int")

        grid = box.grid_flow(columns=2, align=True)
        grid.prop(obj, "cf_enabled")
        grid.prop(obj, "cf_unknown2")
        grid.prop(obj, "cf_unknown3")
        grid.prop(obj, "cf_cast_shadow")
        grid.prop(obj, "cf_unknown5")
        grid.prop(obj, "cf_unknown6")
        grid.prop(obj, "cf_hierarchy")
        grid.prop(obj, "cf_unknown8")

        # =====================================================
        # USER PROPS
        # =====================================================
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
        
        # --- RAW FLAGS INT ---
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
        
        # --- UNIFIED ANIMATION BOX ---
        # Shows shared properties if either animation flag is toggled
        if mat.ls3d_flag_diffuse_animated or mat.ls3d_flag_alpha_animated:
            box_anim = layout.box()
            box_anim.label(text="Texture Animation", icon='ANIM')
            col_anim = box_anim.column(align=True)
            
            col_anim.prop(mat, "ls3d_anim_frames", text="Frames")
            col_anim.prop(mat, "ls3d_anim_period", text="Period (ms)")

        # --- Environment Settings ---
        layout.label(text="Environment Mapping", icon='WORLD_DATA')
        box = layout.box()
        col = box.column(align=True)
        row = col.row()
        row.prop(mat, "ls3d_flag_env_enable")
        #row.prop(mat, "ls3d_flag_envtex")
        row = col.row()
        row.prop(mat, "ls3d_flag_env_overlay")
        row.prop(mat, "ls3d_flag_env_multiply")
        row.prop(mat, "ls3d_flag_env_additive")
        row = col.row()
        row.prop(mat, "ls3d_flag_env_projy")
        row.prop(mat, "ls3d_flag_env_detaily")
        row.prop(mat, "ls3d_flag_env_detailz")

        layout.separator()
        layout.operator("node.add_ls3d_env_setup", icon='NODETREE', text="Add Environment Reflection Setup")
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

    # Interface
    if not ng.interface.items_tree:
        ng.interface.new_socket("Diffuse Map", in_out='INPUT', socket_type='NodeSocketColor')
        ng.interface.new_socket("Alpha Map", in_out='INPUT', socket_type='NodeSocketColor')
        ng.interface.new_socket("Environment Map", in_out='INPUT', socket_type='NodeSocketColor')
        ng.interface.new_socket("Opacity", in_out='INPUT', socket_type='NodeSocketFloat')

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
    def __init__(self, filepath, objects, operator):
        self.filepath = filepath
        self.objects_to_export = objects
        self.operator = operator
        self.materials = []
        self.objects = []
        self.version = VERSION_MAFIA
        self.frames_map = {}
        self.joint_map = {}
        self.frame_index = 1
        self.lod_map = {}

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
        materials = []
        seen = set()

        for obj in self.objects_to_export:
            
            # --- CASE A: Standard Meshes ---
            if obj.type == 'MESH':
                mesh = obj.data
                if not mesh:
                    continue

                for poly in mesh.polygons:
                    mat_index = poly.material_index
                    if mat_index < 0 or mat_index >= len(obj.material_slots):
                        continue

                    mat = obj.material_slots[mat_index].material
                    if mat and mat not in seen:
                        materials.append(mat)
                        seen.add(mat)

            # --- CASE B: Lens Flares (Empties) ---
            # These store the material in a specific property, not in slots.
            # We check if the property exists and is not None.
            mat = getattr(obj, "ls3d_glow_material", None)
            if mat and mat not in seen:
                materials.append(mat)
                seen.add(mat)

        return materials


    
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

        EPS = 1e-3

        # -------------------------------------------------
        # BASIC OBJECT VALIDATION
        # -------------------------------------------------
        if obj.type != 'MESH':
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' must be a MESH object."
            )
            raise RuntimeError("4DS export validation failed")

        if not hasattr(obj, "visual_type") or int(obj.visual_type) != VISUAL_MIRROR:
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' visual type must be VISUAL_MIRROR."
            )
            raise RuntimeError("4DS export validation failed")

        if not obj.data or len(obj.data.vertices) == 0 or len(obj.data.polygons) == 0:
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' mesh has no geometry."
            )
            raise RuntimeError("4DS export validation failed")

        # -------------------------------------------------
        # VIEWBOX VALIDATION
        # -------------------------------------------------
        viewboxes = [
            c for c in obj.children
            if c.name.lower().endswith("_viewbox")
        ]

        if len(viewboxes) == 0:
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' must have exactly ONE '*_viewbox' child (found none)."
            )
            raise RuntimeError("4DS export validation failed")

        if len(viewboxes) > 1:
            names = ", ".join(v.name for v in viewboxes)
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' has multiple viewboxes ({names}). Only ONE is allowed."
            )
            raise RuntimeError("4DS export validation failed")

        vb = viewboxes[0]

        # -------------------------------------------------
        # VIEWBOX OBJECT RULES
        # -------------------------------------------------
        if vb.type != 'EMPTY':
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' viewbox '{vb.name}' must be an EMPTY object."
            )
            raise RuntimeError("4DS export validation failed")

        if vb.empty_display_type != 'CUBE':
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' viewbox '{vb.name}' must use CUBE display type."
            )
            raise RuntimeError("4DS export validation failed")

        if vb.parent != obj:
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' viewbox '{vb.name}' must be a DIRECT child of the mirror object."
            )
            raise RuntimeError("4DS export validation failed")

        if len(vb.children) > 0:
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' viewbox '{vb.name}' must not have child objects."
            )
            raise RuntimeError("4DS export validation failed")

        # -------------------------------------------------
        # MIRROR ORIENTATION VALIDATION
        # -------------------------------------------------
        mesh = obj.data

        # --- Average face normal (LOCAL space) ---
        avg_normal = Vector((0.0, 0.0, 0.0))
        for poly in mesh.polygons:
            avg_normal += poly.normal

        if avg_normal.length == 0.0:
            self.operator.report(
                {'ERROR'},
                f"Mirror '{obj.name}' has invalid face normals."
            )
            raise RuntimeError("4DS export validation failed")

        avg_normal.normalize()

        expected_face = Vector((0.0, 1.0, 0.0))  # +Y

        # Face MUST point +Y
        if avg_normal.dot(expected_face) < 0.99:
            self.operator.report(
                {'WARNING'},
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
            self.operator.report(
                {'WARNING'},
                f"Mirror '{obj.name}' local +X axis is not perpendicular to mirror face.\n"
                "Expected +X to point left. Reflection may be mirrored sideways."
            )

        # +Z should be UP
        if local_z.dot(Vector((0.0, 0.0, 1.0))) < 0.99:
            self.operator.report(
                {'WARNING'},
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
                self.operator.report(
                    {'ERROR'},
                    f"Export stopped: Occluder '{obj.name}' is not a CLOSED mesh."
                )
                raise RuntimeError("4DS export validation failed")

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
                        self.operator.report(
                            {'ERROR'},
                            f"Export stopped: Occluder '{obj.name}' is NOT convex."
                        )
                        raise RuntimeError("4DS export validation failed")

            if inward_ok and not outward_ok:
                self.operator.report(
                    {'WARNING'},
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

        CONVEX_TOLERANCE = 0.01
        PLANAR_EPS = 1e-4

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
                    self.operator.report(
                        {'ERROR'},
                        f"Export stopped: Portal '{obj.name}' has too few vertices."
                    )
                    raise RuntimeError("4DS export validation failed")

                if len(bm.verts) > 8:
                    self.operator.report(
                        {'ERROR'},
                        f"Export stopped: Portal '{obj.name}' exceeds 8 vertex limit."
                    )
                    raise RuntimeError("4DS export validation failed")

                # Planarity check
                v0 = bm.verts[0].co
                plane_normal = None

                for i in range(1, len(bm.verts) - 1):
                    n = (bm.verts[i].co - v0).cross(bm.verts[i + 1].co - v0)
                    if n.length > 1e-6:
                        plane_normal = n.normalized()
                        break

                if plane_normal is None:
                    self.operator.report(
                        {'ERROR'},
                        f"Export stopped: Portal '{obj.name}' is degenerate."
                    )
                    raise RuntimeError("4DS export validation failed")

                for v in bm.verts:
                    if abs((v.co - v0).dot(plane_normal)) > PLANAR_EPS:
                        self.operator.report(
                            {'ERROR'},
                            f"Export stopped: Portal '{obj.name}' is not planar."
                        )
                        raise RuntimeError("4DS export validation failed")

                return 

            # -------------------------------------------------
            # SECTOR VALIDATION (REAL SECTOR ONLY)
            # -------------------------------------------------
            open_edges = [e for e in bm.edges if len(e.link_faces) != 2]
            if open_edges:
                self.operator.report(
                    {'ERROR'},
                    f"Export stopped: Sector '{obj.name}' is not a CLOSED mesh."
                )
                raise RuntimeError("4DS export validation failed")

            if len(bm.faces) < 4:
                self.operator.report(
                    {'ERROR'},
                    f"Export stopped: Sector '{obj.name}' is not a volume."
                )
                raise RuntimeError("4DS export validation failed")

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
                        self.operator.report(
                            {'ERROR'},
                            f"Export stopped: Sector '{obj.name}' is NOT convex."
                        )
                        raise RuntimeError("4DS export validation failed")

            if outward_ok and not inward_ok:
                self.operator.report(
                    {'WARNING'},
                    f"Sector '{obj.name}' is convex but faces are oriented OUTWARD.\n"
                    "4DS sectors require inward-facing normals."
                )

        finally:
            bm.free()

    def serialize_singlemesh(self, f, obj, num_lods): #FUNTODO
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
                    
    def serialize_morph(self, f, obj, num_lods): #FUNTODO
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

    def serialize_target(self, f, obj): #FUNTODO
        f.write(struct.pack("<H", 0))
        link_ids = obj.get("link_ids", [])
        f.write(struct.pack("<B", len(link_ids)))
        if link_ids:
            f.write(struct.pack(f"<{len(link_ids)}H", *link_ids))

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

    def serialize_joint(self, f, bone, armature, parent_id): #FUNTODO
        matrix = bone.matrix_local.copy()
        matrix[1], matrix[2] = matrix[2].copy(), matrix[1].copy()
        flat = [matrix[i][j] for i in range(4) for j in range(3)]
        f.write(struct.pack("<12f", *flat))
        bone_idx = list(armature.data.bones).index(bone)
        f.write(struct.pack("<I", bone_idx))
    
    def serialize_frame(self, f, obj):
        # =================================================
        # 1. FRAME TYPE (NO FORCING)
        # =================================================
        frame_type = int(getattr(obj, "ls3d_frame_type", FRAME_VISUAL))

        # -------------------------------------------------
        # SKIP MIRROR VIEWBOX (STRUCTURAL, NOT A FIX)
        # -------------------------------------------------
        if (
            obj.name.lower().endswith("_viewbox")
            and obj.parent
            and hasattr(obj.parent, "visual_type")
            and int(obj.parent.visual_type) == VISUAL_MIRROR
        ):
            return

        # =================================================
        # 2. VISUAL HEADER (AS-IS)
        # =================================================
        visual_type = 0
        visual_flags = (0, 0)

        if frame_type == FRAME_VISUAL:
            visual_type = int(getattr(obj, "visual_type", 0))
            visual_flags = (
                getattr(obj, "render_flags", 0),
                getattr(obj, "render_flags2", 0),
            )

        # =================================================
        # 3. PARENT LOOKUP
        # =================================================
        parent_id = 0
        is_parent_sector = False

        if obj.parent:
            if obj.parent_type == 'BONE' and obj.parent_bone:
                parent_id = self.joint_map.get(obj.parent_bone, 0)

            elif obj.parent in self.frames_map:
                parent_id = self.frames_map[obj.parent]
                p_type = int(getattr(obj.parent, "ls3d_frame_type", FRAME_VISUAL))
                is_parent_sector = (p_type == FRAME_SECTOR)

        self.frames_map[obj] = self.frame_index
        self.frame_index += 1

        # =================================================
        # 4. TRANSFORM RESOLUTION (NO OVERRIDES)
        # =================================================
        use_direct = not (
            frame_type == FRAME_SECTOR
            or obj.parent_type == 'BONE'
            or is_parent_sector
        )

        if use_direct:
            loc = obj.location
            scl = obj.scale
            rot = obj.rotation_quaternion
        else:
            if frame_type == FRAME_SECTOR:
                mat = obj.matrix_world
            elif obj.parent_type == 'BONE':
                arm = obj.parent
                bone = arm.data.bones[obj.parent_bone]
                parent_mat = arm.matrix_world @ bone.matrix_local
                mat = parent_mat.inverted() @ obj.matrix_world
            elif is_parent_sector:
                mat = obj.matrix_world
            else:
                mat = obj.matrix_local

            loc, rot, scl = mat.decompose()

        # =================================================
        # 5. BLENDER - MAFIA COORDS (PURE CONVERSION)
        # =================================================
        final_pos = Vector((loc.x, loc.z, loc.y))
        final_scl = Vector((scl.x, scl.z, scl.y))

        w = rot.w
        x = rot.x
        y = rot.z
        z = rot.y

        cull_flags = getattr(obj, "cull_flags", 0)

        # =================================================
        # 6. WRITE FRAME HEADER
        # =================================================
        f.write(struct.pack("<B", frame_type))

        if frame_type == FRAME_VISUAL:
            f.write(struct.pack("<B", visual_type))
            f.write(struct.pack("<2B", *visual_flags))

        f.write(struct.pack("<H", parent_id))
        f.write(struct.pack("<3f", final_pos.x, final_pos.y, final_pos.z))
        f.write(struct.pack("<3f", final_scl.x, final_scl.y, final_scl.z))
        f.write(struct.pack("<4f", w, x, y, z))
        f.write(struct.pack("<B", cull_flags))

        self.write_string(f, obj.name)
        self.write_string(f, getattr(obj, "ls3d_user_props", ""))

        # =================================================
        # 7. FRAME PAYLOAD
        # =================================================

        # ---------------- VISUAL ----------------
        if frame_type == FRAME_VISUAL:
            if visual_type == VISUAL_LENSFLARE:
                self.serialize_lensflare(f, obj)
                return

            if obj.type == 'MESH':
                if visual_type == VISUAL_MIRROR:
                    self.validate_mirror(obj)
                    self.serialize_mirror(f, obj)
                    return

                lods = self.lod_map.get(obj, [obj])
                num = self.serialize_object(f, obj, lods)

                if visual_type == VISUAL_BILLBOARD:
                    self.serialize_billboard(f, obj)

                elif visual_type == VISUAL_SINGLEMESH:
                    self.serialize_singlemesh(f, obj, num)

                elif visual_type == VISUAL_SINGLEMORPH:
                    self.serialize_singlemesh(f, obj, num)
                    self.serialize_morph(f, obj, num)

                elif visual_type == VISUAL_MORPH:
                    self.serialize_morph(f, obj, num)

        # ---------------- SECTOR ----------------
        elif frame_type == FRAME_SECTOR:
            self.validate_sector_and_portal(obj)
            self.serialize_sector(f, obj)

        # ---------------- DUMMY ----------------
        elif frame_type == FRAME_DUMMY:
            self.serialize_dummy(f, obj)

        # ---------------- TARGET ----------------
        elif frame_type == FRAME_TARGET:
            self.serialize_target(f, obj)

        # ---------------- OCCLUDER ----------------
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
            ftype = getattr(child, "ls3d_frame_type_override", 0)
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

        flags = flags_unsigned  # always use unsigned for testing

        # -------------------------------------------------
        # 2. COLORS
        # -------------------------------------------------
        amb = getattr(mat, "ls3d_ambient_color", (0.5, 0.5, 0.5))
        dif = getattr(mat, "ls3d_diffuse_color", (1.0, 1.0, 1.0))
        emi = getattr(mat, "ls3d_emission_color", (0.0, 0.0, 0.0))
        opacity = 1.0

        env_amount = 0.0
        diff_tex = ""
        alpha_tex = ""
        env_tex = ""

        if mat.use_nodes:
            main_node = next(
                (n for n in mat.node_tree.nodes
                if n.type == 'GROUP' and "LS3D Material Data" in n.node_tree.name),
                None
            )

            if main_node:
                opacity = main_node.inputs["Opacity"].default_value / 100.0

                d, _ = self.get_tex(main_node, "Diffuse Map")
                a, _ = self.get_tex(main_node, "Alpha Map")
                e, env_amount = self.get_tex(main_node, "Environment Map")

                diff_tex = d or ""
                alpha_tex = a or ""
                env_tex = e or ""

        f.write(struct.pack("<3f", *amb))
        f.write(struct.pack("<3f", *dif))
        f.write(struct.pack("<3f", *emi))
        f.write(struct.pack("<f", opacity))

        # -------------------------------------------------
        # 3. FLAG TESTS (UNSIGNED!)
        # -------------------------------------------------
        env_enabled   = (flags & MTL_ENV_ENABLE) != 0
        alpha_enabled = (flags & MTL_ALPHA_ENABLE) != 0
        alpha_tex_flag = (flags & MTL_ALPHATEX) != 0
        image_alpha   = (flags & MTL_ALPHA_IN_TEX) != 0
        color_key     = (flags & MTL_ALPHA_COLORKEY) != 0
        additive      = (flags & MTL_ALPHA_ADDITIVE) != 0
        animated_diff = (flags & MTL_DIFFUSE_ANIMATED) != 0

        # -------------------------------------------------
        # 4. ENVIRONMENT (only if importer would read it)
        # -------------------------------------------------
        if env_enabled:
            f.write(struct.pack("<f", env_amount))
            self.write_string(f, env_tex.upper())

        # -------------------------------------------------
        # 5. DIFFUSE (ALWAYS write length byte!)
        # -------------------------------------------------
        diffuse_name = diff_tex.upper()
        diffuse_count = self.write_string(f, diffuse_name)

        # -------------------------------------------------
        # 6. ALPHA (EXACT SAME CONDITION AS IMPORTER)
        # -------------------------------------------------
        if (
            diffuse_count > 0 and
            alpha_enabled and
            alpha_tex_flag and
            not image_alpha and
            not color_key and
            not additive
        ):
            self.write_string(f, alpha_tex.upper())

        # -------------------------------------------------
        # 7. ANIMATION (exactly matches importer)
        # -------------------------------------------------
        if animated_diff:
            f.write(struct.pack("<I", mat.ls3d_anim_frames))
            f.write(struct.pack("<H", 0)) # unknown 1
            f.write(struct.pack("<I", mat.ls3d_anim_period))
            f.write(struct.pack("<I", 0))  # unknown 2
            f.write(struct.pack("<I", 0))  # unknown 3

    def serialize_object(self, f, obj, lods):
        """
        4DS v29 geometry exporter (Mafia)
        - Stable topology (no exploded meshes)
        - Correct smooth + flat shading
        - Flat shading achieved by splitting edges between flat faces
        - Matches Max4DSTools behavior
        """

        # Instance ID (0 = unique geometry)
        f.write(struct.pack("<H", 0))

        # LOD count
        f.write(struct.pack("<B", len(lods)))

        depsgraph = bpy.context.evaluated_depsgraph_get()

        for lod_obj in lods:
            # -------------------------------------------------
            # 1. LOD distance
            # -------------------------------------------------
            dist = getattr(lod_obj, "ls3d_lod_dist", 0.0)
            f.write(struct.pack("<f", float(dist)))

            # -------------------------------------------------
            # 2. Get evaluated mesh
            # -------------------------------------------------
            eval_obj = lod_obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()

            bm = bmesh.new()
            bm.from_mesh(mesh)

            # Ensure triangulation (4DS requires triangles)
            bmesh.ops.triangulate(bm, faces=bm.faces)

            # -------------------------------------------------
            # 3. FLAT SHADING HANDLING (CRITICAL PART)
            # -------------------------------------------------
            # Split edges where faces must NOT share normals
            # This is how 4DS / Max creates sharp edges
            edges_to_split = []

            for e in bm.edges:
                if len(e.link_faces) != 2:
                    continue

                f1, f2 = e.link_faces

                # If either face is flat - split edge
                if not f1.smooth or not f2.smooth:
                    edges_to_split.append(e)

            if edges_to_split:
                bmesh.ops.split_edges(bm, edges=edges_to_split)

            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            # -------------------------------------------------
            # 4. Build vertex buffer (NO manual deduplication)
            # -------------------------------------------------
            verts = [v.co.copy() for v in bm.verts]
            num_verts = len(verts)

            if num_verts > 65535:
                bm.free()
                eval_obj.to_mesh_clear()
                self.operator.report(
                    {'ERROR'},
                    f"Object '{lod_obj.name}' exceeds 65535 vertex limit."
                )
                return 0

            f.write(struct.pack("<H", num_verts))

            # Calculate normals AFTER splitting
            bm.normal_update()

            # Write vertices
            for v in bm.verts:
                p = v.co
                n = v.normal

                # Position (X, Z, Y)
                f.write(struct.pack("<3f", p.x, p.z, p.y))

                # Normal (X, Z, Y)
                f.write(struct.pack("<3f", n.x, n.z, n.y))

                # UVs - take first loop UV (safe after split)
                uv = (0.0, 0.0)
                if mesh.uv_layers.active:
                    for loop in v.link_loops:
                        uv_raw = mesh.uv_layers.active.data[loop.index].uv
                        uv = (uv_raw.x, 1.0 - uv_raw.y)
                        break

                f.write(struct.pack("<2f", uv[0], uv[1]))

            # -------------------------------------------------
            # 5. Write faces grouped by material
            # -------------------------------------------------
            mat_groups = {}

            for face in bm.faces:
                mat_idx = face.material_index
                mat_groups.setdefault(mat_idx, []).append(face)

            f.write(struct.pack("<B", len(mat_groups)))

            for mat_idx in sorted(mat_groups.keys()):
                faces = mat_groups[mat_idx]

                f.write(struct.pack("<H", len(faces)))

                for face in faces:
                    v0, v1, v2 = face.verts
                    # Winding: Blender - Mafia (0,2,1)
                    f.write(struct.pack("<3H", v0.index, v2.index, v1.index))

                # Material ID (1-based)
                mat_id = 0
                if 0 <= mat_idx < len(lod_obj.material_slots):
                    mat = lod_obj.material_slots[mat_idx].material
                    if mat in self.materials:
                        mat_id = self.materials.index(mat) + 1

                f.write(struct.pack("<H", mat_id))

            # -------------------------------------------------
            # Cleanup
            # -------------------------------------------------
            bm.free()
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
        """
        Mafia v29 mirror export.
        Byte-for-byte compatible with Max4DSTools.
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
            # 5. VIEWBOX MATRIX (EXACT MAX4DS LAYOUT)
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


    def serialize_joints(self, f, armature): #FUNTODO
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
                self.serialize_material(f, mat, i) # + 1 ale hned za i

            # 2. Identify Special Objects
            lod_objects_set = self.collect_lods()

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

            mirror_viewboxes = set()

            for obj in self.objects_to_export:
                if (
                    obj.type == 'EMPTY'
                    and obj.empty_display_type == 'CUBE'
                    and int(getattr(obj, "ls3d_frame_type", '1')) == FRAME_DUMMY
                    and obj.parent
                    and hasattr(obj.parent, "visual_type")
                    and int(obj.parent.visual_type) == VISUAL_MIRROR
                    and obj.name.lower().endswith("_viewbox")
                ):
                    mirror_viewboxes.add(obj)


            # 3. Build Main Frame List
            scene_names = set(o.name for o in bpy.context.scene.objects)

            raw_objects = [
                obj for obj in self.objects_to_export
                if obj.name in scene_names
                and obj not in lod_objects_set
                and obj not in portal_objects
                and obj not in mirror_viewboxes
                and obj.type in ("MESH", "EMPTY", "ARMATURE")
            ]

            # 4. Hierarchy Sort
            self.objects = []
            roots = [o for o in raw_objects if (not o.parent) or (o.parent not in raw_objects)]

            def sort_hierarchy(obj):
                if obj in self.objects:
                    return
                self.objects.append(obj)
                for child in [c for c in obj.children if c in raw_objects]:
                    sort_hierarchy(child)

            for root in roots:
                sort_hierarchy(root)

            leftovers = [o for o in raw_objects if o not in self.objects]
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

            # 7. Animated objects count
            anim_count = int(getattr(bpy.context.scene, "ls3d_animated_object_count", 0)) & 0xFF
            f.write(struct.pack("<B", anim_count))

        # Only return the path
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
        self.frame_transforms = {}
        self.mafia_raw_transforms = {}

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
                    return
                
                self.version = struct.unpack("<H", f.read(2))[0]
                if self.version != 29: # VERSION_MAFIA
                    print(f"Error: Unsupported 4DS version {self.version}. Only version 29 is supported.")
                    return
                
                f.read(8) # Skip Time

                # 2. Materials
                mat_count = struct.unpack("<H", f.read(2))[0]
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
                
                # Check Animated object count
                try:
                    f.seek(-1, 2)
                    last_byte = f.read(1)
                    if last_byte:
                        anim_count = struct.unpack("<B", last_byte)[0]
                        bpy.context.scene.ls3d_animated_object_count = anim_count
                        print(f"  > Animated object count: {anim_count}")
                except Exception as e:
                    print(f"  > Warning reading animated object count: {e}")

                
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

    def parent_to_bone(self, obj, bone_name): #FUNTODO
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

    def build_armature(self): #FUNTODO
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
    
    def apply_skinning(self, mesh, vertex_groups, bone_to_parent): #FUNTODO
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
    
    def deserialize_singlemesh(self, f, num_lods, mesh): #FUNTODO
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

    def deserialize_target(self, f, empty, pos, rot, scale): #FUNTODO
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
    
    def deserialize_morph(self, f, mesh, num_vertices_per_lod): #FUNTODO
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
            if frame_index not in self.frames_map or parent_id not in self.frames_map: continue
            if frame_index == parent_id: continue

            child_obj = self.frames_map[frame_index]
            parent_entry = self.frames_map[parent_id]
            parent_type = self.frame_types.get(parent_id, 0)

            if child_obj is None or isinstance(child_obj, str): continue

            # Joint Parenting
            if parent_type == 10: 
                if self.armature:
                    p_name = self.bones_map.get(parent_id)
                    if p_name and p_name in self.armature.data.bones:
                        self.parent_to_bone(child_obj, p_name)
            
            # Object Parenting
            elif not isinstance(parent_entry, str):
                child_obj.parent = parent_entry
                
                # CRITICAL: Force Identity Inverse.
                # This ensures the values we put in the UI (Local) are exactly 
                # equal to the file's values (Relative).
                child_obj.matrix_parent_inverse = Matrix.Identity(4)

        # 2. Apply Transforms DIRECTLY
        # Do not use matrix_basis = ... because Blender decomposes it with errors.
        # Set loc/rot/scale properties directly.
        for fid, transform_data in self.frame_transforms.items():
            if fid in self.frames_map:
                obj = self.frames_map[fid]
                if not isinstance(obj, str) and obj is not None:
                    pos, rot, scl = transform_data
                    
                    obj.rotation_mode = 'QUATERNION'
                    obj.location = pos
                    obj.rotation_quaternion = rot
                    obj.scale = scl

    def deserialize_frame(self, f, materials, frames):
        # =================================================
        # 1. READ HEADER & TRANSFORM
        # =================================================
        raw = f.read(1)
        if not raw: return False
        
        frame_type = struct.unpack("<B", raw)[0]
        
        # Init defaults
        visual_type = 0
        visual_flags = (0, 0)
        
        # Read Visual-specific header
        if frame_type == FRAME_VISUAL:
            visual_type = struct.unpack("<B", f.read(1))[0]
            visual_flags = struct.unpack("<2B", f.read(2))
            
        parent_id = struct.unpack("<H", f.read(2))[0]
        
        # Read Transform (Position, Scale, Rotation)
        pos_raw = struct.unpack("<3f", f.read(12))
        scl_raw = struct.unpack("<3f", f.read(12))
        rot_raw = struct.unpack("<4f", f.read(16))
        
        pos = Vector((pos_raw[0], pos_raw[2], pos_raw[1]))
        scl = Vector((scl_raw[0], scl_raw[2], scl_raw[1]))
        rot = Quaternion((rot_raw[0], rot_raw[1], rot_raw[3], rot_raw[2]))
        
        # Store Transform & Hierarchy info
        self.frame_transforms[self.frame_index] = (pos, rot, scl)
        self.frame_matrices[self.frame_index] = Matrix.LocRotScale(pos, rot, scl)
        
        # Read Common Data
        cull_flags = struct.unpack("<B", f.read(1))[0]
        name = self.read_string(f)
        user_props = self.read_string(f)
        
        self.frame_types[self.frame_index] = frame_type
        if parent_id > 0:
            self.parenting_info.append((self.frame_index, parent_id))
            
        # =================================================
        # 2. OBJECT CREATION DISPATCHER
        # =================================================
        obj = None
        
        # --- A. VISUALS ---
        if frame_type == FRAME_VISUAL:
            if visual_type == VISUAL_LENSFLARE:
                # Lensflare creates its own object with custom setup
                obj = self.deserialize_lensflare(f, name, pos, rot, scl)
            else:
                # Standard Mesh Object
                mesh_data = bpy.data.meshes.new(name)
                obj = bpy.data.objects.new(name, mesh_data)
                bpy.context.collection.objects.link(obj)

        # --- B. SECTORS / OCCLUDERS ---
        elif frame_type in (FRAME_SECTOR, FRAME_OCCLUDER):
            mesh_data = bpy.data.meshes.new(name)
            obj = bpy.data.objects.new(name, mesh_data)
            bpy.context.collection.objects.link(obj)

        # --- C. DUMMIES / TARGETS ---
        elif frame_type in (FRAME_DUMMY, FRAME_TARGET):
            obj = bpy.data.objects.new(name, None)
            bpy.context.collection.objects.link(obj)

        # --- D. JOINTS (Special Case: No Object) ---
        elif frame_type == FRAME_JOINT:
            # Skip Joint Payload (Matrix + BoneID)
            f.read(48) # Skip matrix (already calc'd in step 1)
            bone_id = struct.unpack("<I", f.read(4))[0]
            
            if self.armature:
                self.joints.append((name, self.frame_matrices[self.frame_index], parent_id, bone_id))
                self.bone_nodes[bone_id] = name
                self.bones_map[self.frame_index] = name
                
            # Register ID but do not create a Blender Object
            self.frames_map[self.frame_index] = name
            self.frame_index += 1
            return True

        # =================================================
        # 3. PAYLOAD DESERIALIZATION
        # =================================================
        if obj:
            # Register Object
            frames.append(obj)
            self.frames_map[self.frame_index] = obj
            self.frame_index += 1
            
            inst_id = 0
            v_per_lod = []

            # 3a. Frame-Specific Payloads
            if frame_type == FRAME_VISUAL and visual_type != VISUAL_LENSFLARE:
                # Geometry Loading
                if visual_type == VISUAL_MIRROR:
                    self.deserialize_mirror(f, obj)
                else:
                    inst_id, v_per_lod = self.deserialize_object(f, materials, obj, obj.data, cull_flags)
                
                # Visual Logic Payloads (Only for unique instances)
                if inst_id == 0:
                    if visual_type == VISUAL_BILLBOARD:
                        self.deserialize_billboard(f, obj)
                    elif visual_type == VISUAL_SINGLEMESH:
                        self.deserialize_singlemesh(f, len(v_per_lod), obj)
                        # Map base bone for skinning
                        self.bones_map[self.frame_index - 1] = self.base_bone_name
                    elif visual_type in (VISUAL_SINGLEMORPH, VISUAL_MORPH):
                        self.deserialize_morph(f, obj, v_per_lod)

            elif frame_type == FRAME_SECTOR:
                self.deserialize_sector(f, obj)

            elif frame_type == FRAME_DUMMY:
                self.deserialize_dummy(f, obj, pos, rot, scl)

            elif frame_type == FRAME_TARGET:
                self.deserialize_target(f, obj, pos, rot, scl)

            elif frame_type == FRAME_OCCLUDER:
                self.deserialize_occluder(f, obj, pos, rot, scl)

        # =================================================
        # 4. UNIFIED PROPERTY ASSIGNMENT
        # =================================================
        if obj:
            # --- Frame Type ---
            # String for Enum UI
            obj.ls3d_frame_type = str(frame_type) 
            # Int for Logic/Export
            obj.ls3d_frame_type_override = frame_type 
            
            # --- Common Props ---
            obj.cull_flags = cull_flags
            obj.ls3d_user_props = user_props
            
            # --- Visual Specifics ---
            if frame_type == FRAME_VISUAL:
                # String for Enum UI
                obj.visual_type = str(visual_type)
                
                # Render Flags
                obj.render_flags = visual_flags[0]
                obj.render_flags2 = visual_flags[1]

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
        # 6. ALPHA MAP (matches Max4DSTools exactly)
        # -------------------------------------------------
        if (
            len(diffuse_tex_name) > 0 and
            alpha_enabled and
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
            return -1, []

        instance_id = struct.unpack("<H", raw_id)[0]
        if instance_id > 0:
            return instance_id, []

        num_lods = struct.unpack("<B", f.read(1))[0]
        v_counts = []
        
        import math

        for lod_idx in range(num_lods):

            dist = struct.unpack("<f", f.read(4))[0]

            if lod_idx == 0:
                curr_mesh = mesh_data
                target_obj = mesh_obj
            else:
                curr_mesh = bpy.data.meshes.new(f"{mesh_obj.name}_lod{lod_idx}")
                target_obj = bpy.data.objects.new(curr_mesh.name, curr_mesh)
                target_obj.parent = mesh_obj
                bpy.context.collection.objects.link(target_obj)
                target_obj.hide_set(True)
                target_obj.hide_render = True

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

        return 0, v_counts
    
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
        Represented as a cube EMPTY with glow data.
        """

        obj = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(obj)

        obj.empty_display_type = 'CUBE'
        obj.empty_display_size = 0.05  # correct per max4dstools
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
        objects = context.selected_objects if context.selected_objects else context.scene.objects

        exporter = The4DSExporter(self.filepath, objects, operator=self)

        try:
            filepath = exporter.serialize_file()
        except RuntimeError:
            # Error already reported to the user
            return {'CANCELLED'}

        # Only reached if export REALLY succeeded
        self.report(
            {'INFO'},
            f"4DS export successful: {os.path.basename(filepath)}"
        )

        print(f"[4DS EXPORT] Success")
        print(f"[4DS EXPORT] File: {filepath}")

        return {'FINISHED'}
    
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

        for obj in context.scene.objects:
            # 1. If the importer didn't explicitly set a type, detect it
            # (Note: Your importer sets ls3d_frame_type for most things, 
            # so this is mostly for safety or objects created outside the standard flow)
            if obj.ls3d_frame_type == '0': 
                obj.ls3d_frame_type = detect_initial_frame_type(obj)
                
            # 2. Manually trigger the viewport update once to ensure 
            # everything looks correct immediately after import
            ls3d_update_viewport_display(obj)

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

    elif self.type == 'EMPTY' and self.empty_display_type == 'CUBE':
        items = [
            (str(VISUAL_LENSFLARE), "Lens Flare", ""),
        ]

    if not items:
        items = [(str(VISUAL_OBJECT), "Standard", "")]

    return items

import re

def ls3d_update_viewport_display(obj):
    """
    Central viewport display logic for LS3D objects.
    Must be called whenever frame_type or visual_type changes.
    """

    if obj is None:
        return

    # --------------------------------------------------
    # RESET EVERYTHING TO SAFE DEFAULT
    # --------------------------------------------------
    obj.display_type = 'TEXTURED'
    obj.show_wire = False
    obj.show_all_edges = False
    obj.show_axis = False

    # Do NOT touch object.scale here.
    # Do NOT touch empty_display_size globally.

    # --------------------------------------------------
    # Resolve Frame & Visual Types Safely
    # --------------------------------------------------
    try:
        frame_type = int(getattr(obj, "ls3d_frame_type", 0))
    except:
        frame_type = 0

    try:
        visual_type = int(getattr(obj, "visual_type", 0))
    except:
        visual_type = 0

    # ==================================================
    # 1️SECTOR
    # ==================================================
    if frame_type == FRAME_SECTOR and obj.type == 'MESH':

        # --- PORTAL DETECTION ---
        is_portal = (
            obj.type == 'MESH'
                    and int(getattr(obj, "ls3d_frame_type", '1')) == FRAME_SECTOR
                    and obj.parent
                    and int(getattr(obj.parent, "ls3d_frame_type", '1')) == FRAME_SECTOR
                    and re.search(r"_portal\d+$", obj.name, re.IGNORECASE)
        )

        obj.display_type = 'WIRE'
        obj.show_wire = True

        # Portal = wire only
        if not is_portal:
            obj.show_all_edges = True

        return


    # ==================================================
    # 2️OCCLUDER
    # ==================================================
    if frame_type == FRAME_OCCLUDER and obj.type == 'MESH':

        obj.display_type = 'WIRE'
        obj.show_wire = True
        obj.show_all_edges = True
        return


    # ==================================================
    # 3️VISUALS
    # ==================================================
    if frame_type == FRAME_VISUAL:

        # ---------- MIRROR ----------
        if visual_type == VISUAL_MIRROR and obj.type == 'MESH':
            obj.show_axis = True
            return

        # ---------- LENS FLARE ----------
        if visual_type == VISUAL_LENSFLARE and obj.type == 'EMPTY':
            obj.empty_display_type = 'CUBE'
            obj.empty_display_size = 0.05
            return

    # --------------------------------------------------
    # DEFAULT FALLBACK
    # --------------------------------------------------
    # Do nothing more — reset already applied

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

    # --- MODEL ---
    bpy.types.Scene.ls3d_animated_object_count = IntProperty(name="Animated Objects", description="Number of animated objects (0-255)", default=0, min=0, max=255)

    # --- OBJECT PROPERTIES ---
    bpy.types.Object.ls3d_frame_type_override = IntProperty(default=0)

    #bpy.types.Object.ls3d_frame_type = bpy.props.EnumProperty(name="Frame Type", items=frame_type_items, default=0)
    #bpy.types.Object.visual_type = bpy.props.EnumProperty(name="Visual Type", items=visual_type_items, default=0)

    bpy.types.Object.ls3d_frame_type = bpy.props.EnumProperty(name="Frame Type",items=frame_type_items,default=0,update=lambda self, ctx: ls3d_update_viewport_display(self))
    bpy.types.Object.visual_type = bpy.props.EnumProperty(name="Visual Type",items=visual_type_items,default=0,update=lambda self, ctx: ls3d_update_viewport_display(self))
    
    # --- OBJECT CULLING FLAGS ---
    bpy.types.Object.cull_flags = IntProperty(name="Culling Flags", default=0, min=0)
    bpy.types.Object.cf_enabled = BoolProperty(name="Enabled", description="Object is enabled and visible in game", get=make_getter("cull_flags", CF_ENABLED), set=make_setter("cull_flags", CF_ENABLED))
    bpy.types.Object.cf_unknown2 = BoolProperty(name="Unknown 2", description="", get=make_getter("cull_flags", CF_UNKNOWN2), set=make_setter("cull_flags", CF_UNKNOWN2))
    bpy.types.Object.cf_unknown3 = BoolProperty(name="Unknown 3", description="", get=make_getter("cull_flags", CF_UNKNOWN3), set=make_setter("cull_flags", CF_UNKNOWN3))
    bpy.types.Object.cf_cast_shadow = BoolProperty(name="Cast Shadow", description="Object casts shadow on itself", get=make_getter("cull_flags", CF_CAST_SHADOW), set=make_setter("cull_flags", CF_CAST_SHADOW))
    bpy.types.Object.cf_unknown5 = BoolProperty(name="Unknown 5", description="", get=make_getter("cull_flags", CF_UNKNOWN5), set=make_setter("cull_flags", CF_UNKNOWN5))
    bpy.types.Object.cf_unknown6 = BoolProperty(name="Unknown 6", description="", get=make_getter("cull_flags", CF_UNKNOWN6), set=make_setter("cull_flags", CF_UNKNOWN6))
    bpy.types.Object.cf_hierarchy = BoolProperty(name="Hierarchy ?", description="*Object is a parent and has children objects. If disabled, children will be ignored by LS3D*", get=make_getter("cull_flags", CF_HIERARCHY), set=make_setter("cull_flags", CF_HIERARCHY))
    bpy.types.Object.cf_unknown8 = BoolProperty(name="Unknown 8", description="", get=make_getter("cull_flags", CF_UNKNOWN8), set=make_setter("cull_flags", CF_UNKNOWN8))
    
    # --- VISUAL RENDER FLAGS ---
    bpy.types.Object.render_flags = IntProperty(name="Render Flags 1", default=0, min=0)
    bpy.types.Object.render_flags2 = IntProperty(name="Render Flags 2", default=0, min=0)
    
    bpy.types.Object.rf1_unknown1 = BoolProperty(name="Unknown 1", description="", get=make_getter("render_flags", RF_UNKNOWN1), set=make_setter("render_flags", RF_UNKNOWN1))
    bpy.types.Object.rf1_unknown2 = BoolProperty(name="Unknown 2", description="", get=make_getter("render_flags", RF_UNKNOWN2), set=make_setter("render_flags", RF_UNKNOWN2))
    bpy.types.Object.rf1_unknown3 = BoolProperty(name="Unknown 3", description="", get=make_getter("render_flags", RF_UNKNOWN3), set=make_setter("render_flags", RF_UNKNOWN3))
    bpy.types.Object.rf1_unknown4 = BoolProperty(name="Unknown 4", description="", get=make_getter("render_flags", RF_UNKNOWN4), set=make_setter("render_flags", RF_UNKNOWN4))
    bpy.types.Object.rf1_unknown5 = BoolProperty(name="Unknown 5", description="", get=make_getter("render_flags", RF_UNKNOWN5), set=make_setter("render_flags", RF_UNKNOWN5))
    bpy.types.Object.rf1_unknown6 = BoolProperty(name="Unknown 6", description="", get=make_getter("render_flags", RF_UNKNOWN6), set=make_setter("render_flags", RF_UNKNOWN6))
    bpy.types.Object.rf1_unknown7 = BoolProperty(name="Unknown 7", description="", get=make_getter("render_flags", RF_UNKNOWN7), set=make_setter("render_flags", RF_UNKNOWN7))
    bpy.types.Object.rf1_unknown8 = BoolProperty(name="Unknown 8", description="", get=make_getter("render_flags", RF_UNKNOWN8), set=make_setter("render_flags", RF_UNKNOWN8))
    
    bpy.types.Object.rf2_zbias = BoolProperty(name="Z-Bias", description="Object acts as a decal (Poster, picture on a wall). Helps with Z-Fighting on flat surfaces by drawing the object above the surface", get=make_getter("render_flags2", LF_DECAL), set=make_setter("render_flags2", LF_DECAL))
    bpy.types.Object.rf2_recieve_dynamic_shadow = BoolProperty(name="Dynamic Shadows", description="Object can recieve dynamic shadows (eg. from player or vehicle)", get=make_getter("render_flags2", LF_RECIEVE_DYNAMIC_SHADOW), set=make_setter("render_flags2", LF_RECIEVE_DYNAMIC_SHADOW))
    bpy.types.Object.rf2_unknown3 = BoolProperty(name="Unknown 3", description="", get=make_getter("render_flags2", LF_UNKNOWN3), set=make_setter("render_flags2", LF_UNKNOWN3))
    bpy.types.Object.rf2_unknown4 = BoolProperty(name="Unknown 4", description="", get=make_getter("render_flags2", LF_UNKNOWN4), set=make_setter("render_flags2", LF_UNKNOWN4))
    bpy.types.Object.rf2_unknown5 = BoolProperty(name="Unknown 5", description="", get=make_getter("render_flags2", LF_UNKNOWN5), set=make_setter("render_flags2", LF_UNKNOWN5))
    bpy.types.Object.rf2_recieve_projection = BoolProperty(name="Recieve Projection", description="Object recieves projection textures (eg. Car headlights, bullet hole decals)", get=make_getter("render_flags2", LF_RECIEVE_PROJECTION), set=make_setter("render_flags2", LF_RECIEVE_PROJECTION))
    bpy.types.Object.rf2_unknown7 = BoolProperty(name="Unknown 7", description="", get=make_getter("render_flags2", LF_UNKNOWN7), set=make_setter("render_flags2", LF_UNKNOWN7))
    bpy.types.Object.rf2_no_fog = BoolProperty(name="No Fog", description="Object isn't affected by fog", get=make_getter("render_flags2", LF_NO_FOG), set=make_setter("render_flags2", LF_NO_FOG))

    # --- MATERIAL PROPERTIES ---
    bpy.types.Material.ls3d_ambient_color = FloatVectorProperty(subtype='COLOR', default=(0.5,0.5,0.5), name="Ambient")
    bpy.types.Material.ls3d_diffuse_color = FloatVectorProperty(subtype='COLOR', default=(1,1,1), name="Diffuse")
    bpy.types.Material.ls3d_emission_color = FloatVectorProperty(subtype='COLOR', default=(0,0,0), name="Emission")

    # Animations
    bpy.types.Material.ls3d_anim_frames = IntProperty(name="Anim Frames", description="Frame count of the Animated Texture (Maximum is 99)", default=0)
    bpy.types.Material.ls3d_anim_period = IntProperty(name="Anim Period", description="Time (in milliseconds) how long the animation frame stays visible before it changes to the next frame", default=0)

    # --- MATERIAL FLAGS ---
    bpy.types.Material.ls3d_material_flags = IntProperty(name="Material Flags", default=0)
    bpy.types.Material.ls3d_material_flags_str = StringProperty(name="Raw Flags", description="Raw Unsigned Integer", get=get_mat_flags_unsigned, set=set_mat_flags_unsigned)

    # Boolean accessors
    bpy.types.Material.ls3d_flag_misc_unlit = BoolProperty(name="Unlit", description="Disable lighting calculations? Unknown", get=make_getter("ls3d_material_flags", MTL_MISC_UNLIT), set=make_setter("ls3d_material_flags", MTL_MISC_UNLIT))
    bpy.types.Material.ls3d_flag_env_overlay = BoolProperty(name="Mode Overlay", description="Sets the environment texture to Overlay mode", get=make_getter("ls3d_material_flags", MTL_ENV_OVERLAY), set=make_setter("ls3d_material_flags", MTL_ENV_OVERLAY))
    bpy.types.Material.ls3d_flag_env_multiply = BoolProperty(name="Mode Multiply", description="Sets the environment texture to Multiply mode", get=make_getter("ls3d_material_flags", MTL_ENV_MULTIPLY), set=make_setter("ls3d_material_flags", MTL_ENV_MULTIPLY))
    bpy.types.Material.ls3d_flag_env_additive = BoolProperty(name="Mode Additive", description="Sets the environment texture to Additive mode", get=make_getter("ls3d_material_flags", MTL_ENV_ADDITIVE), set=make_setter("ls3d_material_flags", MTL_ENV_ADDITIVE))
    # bpy.types.Material.ls3d_flag_envtex = BoolProperty(name="Environment Texture", description="Enables Environment texture", get=make_getter("ls3d_material_flags", MTL_ENVTEX), set=make_setter("ls3d_material_flags", MTL_ENVTEX))
    bpy.types.Material.ls3d_flag_env_projy = BoolProperty(name="Project on Y", description="Sets the texture to be aligned on the Y axis (Up/Down)", get=make_getter("ls3d_material_flags", MTL_ENV_PROJY), set=make_setter("ls3d_material_flags", MTL_ENV_PROJY))
    bpy.types.Material.ls3d_flag_env_detaily = BoolProperty(name="Detail Y", description="", get=make_getter("ls3d_material_flags", MTL_ENV_DETAILY), set=make_setter("ls3d_material_flags", MTL_ENV_DETAILY))
    bpy.types.Material.ls3d_flag_env_detailz = BoolProperty(name="Detail Z", description="", get=make_getter("ls3d_material_flags", MTL_ENV_DETAILZ), set=make_setter("ls3d_material_flags", MTL_ENV_DETAILZ))
    
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
    bpy.types.Object.rot_mode = EnumProperty(items=(('1','All',''),('2','Single','')), name="Rot Mode")
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
    bpy.types.Object.pf_mirror = BoolProperty(name="Mirror", description="Portal is a Mirror surface", get=make_getter("ls3d_portal_flags", PF_MIRROR), set=make_setter("ls3d_portal_flags", PF_MIRROR))
    bpy.types.Object.pf_unknown1 = BoolProperty(name="Unknown 1", description="", get=make_getter("ls3d_portal_flags", PF_UNKNOWN1), set=make_setter("ls3d_portal_flags", PF_UNKNOWN1))
    bpy.types.Object.pf_unknown2 = BoolProperty(name="Unknown 2", description="", get=make_getter("ls3d_portal_flags", PF_UNKNOWN2), set=make_setter("ls3d_portal_flags", PF_UNKNOWN2))

    # Mirror Props
    bpy.types.Object.ls3d_mirror_color = bpy.props.FloatVectorProperty(name="Mirror Color", subtype='COLOR', size=3, min=0.0, max=1.0, default=(1.0, 1.0, 1.0))
    bpy.types.Object.ls3d_mirror_range = bpy.props.FloatProperty(name="Mirror Active Range", min=0.0, default=0.0)

    # Lensflare Props
    bpy.types.Object.ls3d_glow_position = bpy.props.FloatProperty(name="Position", description="Screen offset (Mafia lens flare)", default=0.0)
    bpy.types.Object.ls3d_glow_material = bpy.props.PointerProperty(name="Material", description="Lens flare material", type=bpy.types.Material)


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
    
    del bpy.types.Scene.ls3d_animated_object_count
    
    del bpy.types.Object.ls3d_portal_normal
    del bpy.types.Object.ls3d_portal_dot

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
    del bpy.types.Object.cf_node_hierarchy
    del bpy.types.Object.render_flags
    del bpy.types.Object.render_flags2
    del bpy.types.Object.rf1_cast_shadow
    del bpy.types.Object.rf1_receive_shadow
    del bpy.types.Object.rf1_draw_last
    del bpy.types.Object.rf1_zbias
    del bpy.types.Object.rf1_bright
    del bpy.types.Object.rf2_zbias
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
    
    # Animation
    del bpy.types.Material.ls3d_anim_frames
    del bpy.types.Material.ls3d_anim_period

    # Material Flags
    del bpy.types.Material.ls3d_material_flags
    del bpy.types.Material.ls3d_material_flags_str
    del bpy.types.Material.ls3d_flag_misc_unlit
    del bpy.types.Material.ls3d_flag_env_overlay
    del bpy.types.Material.ls3d_flag_env_multiply
    del bpy.types.Material.ls3d_flag_env_additive
    #del bpy.types.Material.ls3d_flag_envtex
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

    del bpy.types.Object.ls3d_mirror_color
    del bpy.types.Object.ls3d_mirror_range

    bpy.utils.unregister_class(LS3D_OT_AddEnvSetup)
    bpy.utils.unregister_class(LS3D_OT_AddNode)
    bpy.utils.unregister_class(The4DSPanelMaterial)
    bpy.utils.unregister_class(The4DSPanel)
    bpy.utils.unregister_class(Import4DS)
    bpy.utils.unregister_class(Export4DS)

if __name__ == "__main__":
    register()