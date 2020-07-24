# Addon Info
bl_info = {
    "name": "Real Camera",
    "description": "Physical camera controls",
    "author": "Wolf <wolf.art3d@gmail.com>",
    "version": (3, 2),
    "blender": (2, 83, 0),
    "location": "View 3D > Properties Panel",
    "doc_url": "https://github.com/macio97/Real-Camera",
    "tracker_url": "https://github.com/macio97/Real-Camera/issues",
    "support": "COMMUNITY",
    "category": "Render",
    }


# Libraries
import bpy
import bgl
import os
from math import ceil, log2, pow
from mathutils import Vector
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import PropertyGroup, Panel, Operator


# Real Camera panel
class REALCAMERA_PT_Panel(Panel):
    bl_category = "Real Camera"
    bl_label = "Real Camera"
    bl_space_type = 'PROPERTIES'
    bl_region_type = "WINDOW"
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        return context.camera

    def draw_header(self, context):
        settings = context.scene.camera_settings
        layout = self.layout
        layout.prop(settings, 'enabled', text='')

    def draw(self, context):
        settings = context.scene.camera_settings
        cam = context.camera
        layout = self.layout
        layout.enabled = settings.enabled

        # Exposure triangle
        layout.use_property_split = True
        layout.use_property_decorate = False
        flow = layout.grid_flow(row_major=True, columns=0, even_columns=False, even_rows=False, align=True)
        col = flow.column()
        sub = col.column(align=True)
        sub.prop(cam.dof, "aperture_fstop", text="Aperture")
        sub.prop(settings, 'shutter_speed')

        # Mechanics
        col = flow.column()
        col.prop(settings, 'enable_af')
        if settings.enable_af:
            row = col.row(align=True)
            row.prop(settings, 'af_step', text="Bake")
            row.prop(settings, 'af_bake', text="", icon='PLAY')
        col = flow.column()
        sub = col.column(align=True)
        if not settings.enable_af:
            sub.prop(cam.dof, "focus_distance", text="Focus Point")
        sub.prop(cam, 'lens', text="Focal Length")


# Auto Exposure panel
class AUTOEXP_PT_Panel(Panel):
    bl_space_type = "PROPERTIES"
    bl_context = "render"
    bl_region_type = "WINDOW"
    bl_category = "Real Camera"
    bl_label = "Auto Exposure"
    COMPAT_ENGINES = {'BLENDER_EEVEE', 'CYCLES'}

    @classmethod
    def poll(cls, context):
        return (context.engine in cls.COMPAT_ENGINES)

    def draw_header(self, context):
        settings = context.scene.camera_settings
        layout = self.layout
        layout.prop(settings, 'enable_ae', text='')

    def draw(self, context):
        settings = context.scene.camera_settings
        layout = self.layout
        layout.enabled = settings.enable_ae

        # Modes
        col = layout.column(align=True)
        row = col.row(align=True)
        row.alignment = "CENTER"
        row.label(text="Metering Mode")
        row = col.row(align=True)
        row.scale_x = 1.5
        row.scale_y = 1.5
        row.alignment = "CENTER"
        row.prop(settings, 'ae_mode', text="", expand=True)
        col.label(text="")

        # Settings
        layout.use_property_split = True
        layout.use_property_decorate = False
        flow = layout.grid_flow(row_major=True, columns=0, even_columns=False, even_rows=False, align=True)
        col = flow.column()
        col.prop(settings, 'ev_compensation', slider=True)
        if settings.ae_mode=="Center Weighed":
            col.prop(settings, 'center_grid')
        if settings.ae_mode=="Full Window":
            col.prop(settings, 'full_grid')


def enable_camera(self, context):
	settings = context.scene.camera_settings
	name = context.active_object.name
	if settings.enabled:
		# set limits
		bpy.data.cameras[name].show_limits = True
		# enable DOF
		context.object.data.dof.use_dof = True
		# set camera size
		bpy.context.object.data.display_size = 0.2
		# set initial values
		update_aperture(self, context)
		update_shutter_speed(self, context)
	else:
		# disable DOF
		context.object.data.dof.use_dof = False
		# disable limits
		bpy.data.cameras[name].show_limits = False
		# disable autofocus
		bpy.context.scene.camera_settings.enable_af = False


def update_aperture(self, context):
    context.object.data.cycles.aperture_fstop = context.scene.camera_settings.aperture


def update_shutter_speed(self, context):
    fps = context.scene.render.fps
    shutter = context.scene.camera_settings.shutter_speed
    motion = fps * shutter
    context.scene.render.motion_blur_shutter = motion


def update_autofocus(self, context):
    autofocus = context.scene.camera_settings.enable_af

    if autofocus:
        name = context.active_object.name
        obj = bpy.data.objects[name]
        # ray cast
        ray = context.scene.ray_cast(context.scene.view_layers[0], obj.location, obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0)))
        distance = (ray[1] - obj.location).magnitude
        bpy.context.object.data.dof.focus_distance = distance
    else:
        # reset baked af
        context.scene.camera_settings.af_bake = False
        autofocus_bake(self, context)


def autofocus_bake(self, context):
    scene = bpy.context.scene
    bake = scene.camera_settings.af_bake
    start = scene.frame_start
    end = scene.frame_end
    frames = end - start + 1
    steps = scene.camera_settings.af_step
    n = int(float(frames / steps))
    current_frame = scene.frame_current
    name = context.active_object.name
    cam = bpy.data.cameras[name]
    if bake:
        scene.frame_current = start
        # every step frames, place a keyframe
        for i in range(n + 1):
            update_autofocus(self, context)
            cam.dof.keyframe_insert('focus_distance')
            scene.frame_set(scene.frame_current + steps)
        # current Frame
        scene.frame_current = current_frame
    else:
        # delete dof keyframes
        try:
            fcurves = cam.animation_data.action.fcurves
        except AttributeError:
            a = 0
        else:
            for c in fcurves:
                if c.data_path.startswith("dof.focus_distance"):
                    fcurves.remove(c)


def read_filmic(path):
    nums = []
    with open(path) as filmic_file:
        for line in filmic_file:
            nums.append(float(line))
    return nums


# Globals
path = os.path.join(os.path.dirname(__file__), "looks/")
filmic_vhc = read_filmic(path + "Very High Contrast")
filmic_hc = read_filmic(path + "High Contrast")
filmic_mhc = read_filmic(path + "Medium High Contrast")
filmic_mc = read_filmic(path + "Medium Contrast")
filmic_mlc = read_filmic(path + "Medium Low Contrast")
filmic_lc = read_filmic(path + "Low Contrast")
filmic_vlc = read_filmic(path + "Very Low Contrast")


def auto_exposure():
    shading = bpy.context.area.spaces.active.shading.type

    # check if viewport is set to Rendered mode
    if shading == "RENDERED":
        settings = bpy.context.scene.camera_settings
        # viewport width and height
        viewport = bgl.Buffer(bgl.GL_INT, 4)
        bgl.glGetIntegerv(bgl.GL_VIEWPORT, viewport)
        width = viewport[2]
        height = viewport[3]
        buf = bgl.Buffer(bgl.GL_FLOAT, 3)

        # Center Spot
        if settings.ae_mode=="Center Spot":
            x = width // 2
            y = height // 2
            bgl.glReadPixels(x, y, 1, 1, bgl.GL_RGB, bgl.GL_FLOAT, buf)
            avg = rgb_to_luminance(buf)

        # Full Window
        if settings.ae_mode == "Full Window":
            grid = settings.full_grid
            values = 0
            step = 1 / (grid + 1)
            for i in range (grid):
                for j in range (grid):
                    x = int(step * (j + 1) * width)
                    y = int(step * (i + 1) * height)
                    bgl.glReadPixels(x, y, 1, 1, bgl.GL_RGB, bgl.GL_FLOAT, buf)
                    lum = rgb_to_luminance(buf)
                    values = values + lum
            avg = values / (grid * grid)

        # Center Weighed
        if settings.ae_mode == "Center Weighed":
            circles = settings.center_grid
            if width >= height:
                max = width
            else:
                max = height
            half = max // 2
            step = max // (circles * 2 + 2)
            values = 0
            weights = 0
            for i in range (circles):
                x = half - (i + 1) * step
                y = x
                n_steps = i * 2 + 2
                weight = (circles - 1 - i) / circles
                for n in range (n_steps):
                    x = x + step
                    bgl.glReadPixels(x, y, 1, 1, bgl.GL_RGB, bgl.GL_FLOAT, buf)
                    lum = rgb_to_luminance(buf)
                    values = values + lum * weight
                    weights = weights + weight
                for n in range (n_steps):
                    y = y + step
                    bgl.glReadPixels(x, y, 1, 1, bgl.GL_RGB, bgl.GL_FLOAT, buf)
                    lum = rgb_to_luminance(buf)
                    values = values + lum * weight
                    weights = weights + weight
                for n in range (n_steps):
                    x = x - step
                    bgl.glReadPixels(x, y, 1, 1, bgl.GL_RGB, bgl.GL_FLOAT, buf)
                    lum = rgb_to_luminance(buf)
                    values = values + lum * weight
                    weights = weights + weight
                for n in range (n_steps):
                    y = y - step
                    bgl.glReadPixels(x, y, 1, 1, bgl.GL_RGB, bgl.GL_FLOAT, buf)
                    lum = rgb_to_luminance(buf)
                    values = values + lum * weight
                    weights = weights + weight
            avg = values / weights

        s = avg_min = avg_max = middle = 0

        # if average is not 0 then update exposure
        if avg > 0:
            actual_exposure = bpy.context.scene.view_settings.exposure
            ev_compensation = bpy.context.scene.camera_settings.ev_compensation
            middle_gray = 0.18 * pow(2, ev_compensation)
            scene_exposed = avg * pow(2, actual_exposure)
            log = (log2(scene_exposed / 0.18) + 10) / 16.5
            s = contrast(log)
            log_target = (log2(middle_gray / 0.18) + 10) / 16.5
            s_target = contrast(log_target)
            avg_min = s_target - 0.01
            avg_max = s_target + 0.01
            if not (s > avg_min and s < avg_max):
                future = -log2(avg / middle_gray)
                exposure = actual_exposure - (actual_exposure - future) / 5
                bpy.context.scene.view_settings.exposure = exposure


def contrast(log):
    if log < 1:
        look = bpy.context.scene.view_settings.look
        if look=="None":
            filmic = filmic_mc
        elif look=="Very High Contrast":
            filmic = filmic_vhc
        elif look=="High Contrast":
            filmic = filmic_hc
        elif look=="Medium High Contrast":
            filmic = filmic_mhc
        elif look=="Medium Contrast":
            filmic = filmic_mc
        elif look=="Medium Low Contrast":
            filmic = filmic_mlc
        elif look=="Low Contrast":
            filmic = filmic_lc
        elif look=="Very Low Contrast":
            filmic = filmic_vlc
        x = int(log * 4095)
        return filmic[x]
    else:
        return 1


def rgb_to_luminance(buf):
    lum = 0.2126 * buf[0] + 0.7152 * buf[1] + 0.0722 * buf[2]
    return lum


class AUTOEXP_ae_toggle:
    bl_idname = "autoexp.toggle_ae"
    bl_label = "Enable AE"
    bl_description = "Enable Auto Exposure draw handler"

    _handle = None

    @staticmethod
    def add_handler():
        if AUTOEXP_ae_toggle._handle is None:
            AUTOEXP_ae_toggle._handle = bpy.types.SpaceView3D.draw_handler_add(
                auto_exposure,
                (),
                'WINDOW',
                'PRE_VIEW')

    @staticmethod
    def remove_handler():
        if AUTOEXP_ae_toggle._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(
                AUTOEXP_ae_toggle._handle,
                'WINDOW')
            AUTOEXP_ae_toggle._handle = None

def enable_auto_exposure(self, context):
    ae = context.scene.camera_settings.enable_ae
    if ae:
        AUTOEXP_ae_toggle.add_handler()
    else:
        AUTOEXP_ae_toggle.remove_handler()

class CameraSettings(PropertyGroup):
    # Enable
    enabled : BoolProperty(
        name = "Real Camera",
        description = "Enable Real Camera",
        default = False,
        update = enable_camera
        )

    # Exposure Triangle
    aperture : FloatProperty(
        name = "Aperture",
        description = "Aperture of the lens in f-stops. From 0.1 to 64. Gives a depth of field effect",
        min = 0.1,
        max = 64,
        step = 1,
        precision = 2,
        default = 5.6,
        update = update_aperture
        )

    shutter_speed : FloatProperty(
        name = "Shutter Speed",
        description = "Exposure time of the sensor in seconds. From 1/10000 to 10. Gives a motion blur effect",
        min = 0.0001,
        max = 100,
        step = 10,
        precision = 4,
        default = 0.5,
        update = update_shutter_speed
        )

    # Mechanics
    enable_af : BoolProperty(
        name = "Autofocus",
        description = "Enable Autofocus",
        default = False,
        update = update_autofocus
        )

    af_bake : BoolProperty(
        name = "Autofocus Baking",
        description = "Bake Autofocus for the entire animation",
        default = False,
        update = autofocus_bake
        )

    af_step : IntProperty(
        name = "Step",
        description = "Every step frames insert a keyframe",
        min = 1,
        max = 10000,
        default = 24
        )

    # Auto Exposure
    enable_ae : BoolProperty(
        name = "Auto Exposure",
        description = "Enable Auto Exposure",
        default = False,
        update = enable_auto_exposure
        )

    ae_mode : EnumProperty(
        name="Mode",
        items= [
            ("Center Spot", "Center Spot", "Sample the pixel in the center of the window", 'PIVOT_BOUNDBOX', 0),
            ("Center Weighed", "Center Weighed", "Sample a grid of pixels and gives more weight to the ones near the center", 'CLIPUV_HLT', 1),
            ("Full Window", "Full Window", "Sample a grid of pixels among the whole window", 'FACESEL', 2),
            ],
        description="Select an auto exposure metering mode",
        default="Center Weighed"
        )

    ev_compensation : FloatProperty(
        name = "EV Compensation",
        description = "Exposure Compensation value: add or subtract brightness",
        min = -3,
        max = 3,
        step = 1,
        precision = 2,
        default = 0
        )

    center_grid : IntProperty(
        name = "Circles",
        description = "Number of circles to sample: more circles means more accurate auto exposure, but also means slower viewport",
        min = 2,
        max = 20,
        default = 4
        )

    full_grid : IntProperty(
        name = "Grid",
        description = "Number of rows and columns to sample: more rows and columns means more accurate auto exposure, but also means slower viewport",
        min = 2,
        max = 20,
        default = 7
        )


############################################################################
classes = (
    REALCAMERA_PT_Panel,
    AUTOEXP_PT_Panel,
    CameraSettings
    )

register, unregister = bpy.utils.register_classes_factory(classes)


# Register
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.camera_settings = bpy.props.PointerProperty(type=CameraSettings)


# Unregister
def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.camera_settings

    # Remove draw handler if it exists
    AUTOEXP_ae_toggle.remove_handler()


if __name__ == "__main__":
    register()
