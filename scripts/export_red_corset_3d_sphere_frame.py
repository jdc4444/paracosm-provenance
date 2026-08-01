import os

import bpy


ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance"
OUTPUT = os.path.join(
    ROOT, "public/archive/objects/3d/tests/red-corset-3d-sphere-sim"
)
FRAME = 80

scene = bpy.context.scene
scene.frame_set(FRAME)

corset = bpy.data.objects["Red_Corset_Render_Mesh"]
depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated = corset.evaluated_get(depsgraph)
settled_mesh = bpy.data.meshes.new_from_object(
    evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
)
settled = bpy.data.objects.new(
    "Red_Corset_Invisible_Sphere_Drape_Frame80", settled_mesh
)
bpy.context.collection.objects.link(settled)
settled.matrix_world = corset.matrix_world.copy()

for obj in bpy.context.selected_objects:
    obj.select_set(False)
settled.select_set(True)
bpy.context.view_layer.objects.active = settled
bpy.ops.export_scene.gltf(
    filepath=os.path.join(
        OUTPUT, "red-corset-3d-sphere-sim-frame80.glb"
    ),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
)

settled.hide_viewport = True
settled.hide_render = True
bpy.ops.wm.save_as_mainfile(
    filepath=os.path.join(
        OUTPUT, "red-corset-3d-sphere-sim-frame80.blend"
    )
)

print(
    "CORSET_SPHERE_FRAME_EXPORT_COMPLETE",
    "frame",
    FRAME,
    "faces",
    len(settled_mesh.polygons),
    "output",
    OUTPUT,
)
