"""Run with Blender in a disposable directory; synthetic import fixture, not model QA."""
import sys
from pathlib import Path

import bpy

output = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cube_add()
mesh = bpy.context.object
mesh.name = "ImportPolicyFixture"
mesh.shape_key_add(name="Basis")
shape = mesh.shape_key_add(name="Expression")
for vertex in shape.data:
    if vertex.co.z > 0:
        vertex.co.z += 0.3
shape.value = 0
shape.keyframe_insert("value", frame=1)
shape.value = 1
shape.keyframe_insert("value", frame=12)

bpy.ops.object.armature_add()
rig = bpy.context.object
mesh.parent = rig
modifier = mesh.modifiers.new("Rig", "ARMATURE")
modifier.object = rig
group = mesh.vertex_groups.new(name=rig.data.bones[0].name)
group.add(list(range(len(mesh.data.vertices))), 1.0, "REPLACE")
bone = rig.pose.bones[0]
bone.rotation_mode = "XYZ"
bone.rotation_euler.z = 0
bone.keyframe_insert("rotation_euler", frame=1)
bone.rotation_euler.z = 0.2
bone.keyframe_insert("rotation_euler", frame=12)
bpy.context.scene.frame_end = 12
bpy.context.scene.frame_set(1)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.fbx(
    filepath=str(output), use_selection=True, object_types={"MESH", "ARMATURE"},
    add_leaf_bones=False, bake_anim=True, bake_anim_use_all_actions=False,
    bake_anim_use_nla_strips=False, axis_forward="-Z", axis_up="Y",
)
