import os

import bpy


ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance"
OUTPUT = os.path.join(
    ROOT, "public/archive/objects/3d/tests/red-corset-3d-cage-rail-sim"
)
FRAME = 16

scene = bpy.context.scene
scene.frame_set(FRAME)
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.filepath = os.path.join(
    OUTPUT, "red-corset-3d-cage-rail-sim-frame16.png"
)
bpy.ops.render.render(write_still=True)

corset = bpy.data.objects["Red_Corset_Render_Mesh"]
depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated = corset.evaluated_get(depsgraph)
settled_mesh = bpy.data.meshes.new_from_object(
    evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
)
settled = bpy.data.objects.new("Red_Corset_3D_Drape_Frame16", settled_mesh)
bpy.context.collection.objects.link(settled)
settled.matrix_world = corset.matrix_world.copy()

for obj in bpy.context.selected_objects:
    obj.select_set(False)
settled.select_set(True)
bpy.context.view_layer.objects.active = settled
bpy.ops.export_scene.gltf(
    filepath=os.path.join(
        OUTPUT, "red-corset-3d-cage-rail-sim-frame16.glb"
    ),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
)

settled.hide_viewport = True
settled.hide_render = True
bpy.ops.wm.save_as_mainfile(
    filepath=os.path.join(
        OUTPUT, "red-corset-3d-cage-rail-sim-frame16.blend"
    )
)

print(
    "CORSET_3D_FRAME_EXPORT_COMPLETE",
    "frame",
    FRAME,
    "faces",
    len(settled_mesh.polygons),
    "output",
    OUTPUT,
)
