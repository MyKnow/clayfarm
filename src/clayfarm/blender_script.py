"""Trusted Blender 4.x adapter. Invoked only with local JSON files by ClayFarm.
No eval, exec, arbitrary Blender scripts, or executable content from the queue.
"""
import json
import math
import sys
from pathlib import Path
import bpy
import bmesh
from mathutils import Vector


def write(path,data):
    Path(path).write_text(json.dumps(data,indent=2,allow_nan=False),encoding="utf-8")


def meshes():
    return [o for o in bpy.context.scene.objects if o.type=="MESH"]


def bounds(obj):
    pts=[obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    lo=Vector([min(v[i] for v in pts) for i in range(3)])
    hi=Vector([max(v[i] for v in pts) for i in range(3)])
    return lo,hi


def import_mesh(path):
    if Path(path).suffix.lower()!=".glb": raise ValueError("Only GLB input is accepted")
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs=meshes()
    if not objs: raise ValueError("No mesh in input")
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active=objs[0]
    # Bake world coordinates before joining, including nested/negative transforms.
    for o in objs:
        matrix=o.matrix_world.copy()
        o.data=o.data.copy(); o.data.transform(matrix)
        o.parent=None; o.matrix_world.identity()
    bpy.context.view_layer.update()
    bpy.ops.object.join()
    return bpy.context.active_object


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True); bpy.context.view_layer.objects.active=obj


def triangle_count(obj):
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def cleanup(obj, distance):
    bm=bmesh.new(); bm.from_mesh(obj.data)
    before=len(bm.verts)
    if distance:
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=max(distance, 1e-10))
    loose=[v for v in bm.verts if not v.link_faces]
    if loose: bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    removed=before-len(bm.verts)
    bm.to_mesh(obj.data); bm.free(); obj.data.update()
    if not obj.data.polygons: raise ValueError("Cleanup produced an empty mesh")
    return removed


def normalize(obj, spec):
    obj.data.update(); bpy.context.view_layer.update()
    lo,hi=bounds(obj); height=hi.z-lo.z
    if height<=1e-8: raise ValueError("Mesh height is zero")
    origin=(lo+hi)/2
    if spec["pivot"]=="bottom_center": origin.z=lo.z
    for v in obj.data.vertices: v.co=(v.co-origin)*(spec["height_m"]/height)
    obj.data.update(); bpy.context.view_layer.update()


def budget(obj, target):
    activate(obj)
    for _ in range(4):
        count=triangle_count(obj)
        if count<=target: break
        mod=obj.modifiers.new("ClayFarmBudget","DECIMATE")
        mod.ratio=max(.000001,target/count*.97); mod.use_collapse_triangulate=True
        bpy.ops.object.modifier_apply(modifier=mod.name)
    if not triangle_count(obj): raise ValueError("Decimation produced an empty mesh")


def export_glb(obj, path):
    activate(obj)
    bpy.ops.export_scene.gltf(filepath=str(path),export_format="GLB",use_selection=True,export_yup=True)


def extras(obj, spec, out):
    outputs=[]
    for index,ratio in enumerate(spec.get("lod_ratios", []),1):
        lod=obj.copy(); lod.data=obj.data.copy(); bpy.context.collection.objects.link(lod)
        lod.name=obj.name+f"_LOD{index}"
        target=max(4,int(triangle_count(obj)*ratio)); budget(lod,target)
        name=f"lod{index}.glb"; export_glb(lod,out/name)
        outputs.append({"name":name,"role":"lod","triangles":triangle_count(lod),"target_triangles":target})
        bpy.data.objects.remove(lod,do_unlink=True)
    mode=spec.get("collider","none")
    if mode!="none":
        lo,hi=bounds(obj)
        if mode=="box":
            bpy.ops.mesh.primitive_cube_add(size=1,location=(lo+hi)/2)
            collider=bpy.context.object; collider.dimensions=hi-lo
            bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
        else:
            bm=bmesh.new()
            for v in obj.data.vertices: bm.verts.new(v.co)
            bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
            loose=[v for v in bm.verts if not v.link_faces]
            if loose: bmesh.ops.delete(bm,geom=loose,context="VERTS")
            bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
            data=bpy.data.meshes.new("Collider"); bm.to_mesh(data); bm.free()
            collider=bpy.data.objects.new("Collider",data); bpy.context.collection.objects.link(collider)
            # A dense convex hull is not automatically a usable physics collider.
            # Fall back to the conservative enclosing box (no accidental concavity).
            if triangle_count(collider)>255:
                bpy.data.objects.remove(collider,do_unlink=True)
                bpy.ops.mesh.primitive_cube_add(size=1,location=(lo+hi)/2)
                collider=bpy.context.object; collider.dimensions=hi-lo
                bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
                mode="box_fallback"
        collider.name=obj.name+"_COLLIDER"
        export_glb(collider,out/"collider.glb")
        outputs.append({"name":"collider.glb","role":"collider","type":mode,"triangles":triangle_count(collider)})
        bpy.data.objects.remove(collider,do_unlink=True)
    activate(obj)
    return outputs


def process(params):
    spec=params["spec"]; out=Path(params["output"])
    obj=import_mesh(params["input"])
    obj.name=spec["name"]
    if not obj.data.vertices: raise ValueError("Empty mesh")
    initial_triangles=triangle_count(obj)
    for v in obj.data.vertices:
        if not all(math.isfinite(x) for x in v.co): raise ValueError("Non-finite mesh coordinates")
        for axis in range(3): v.co[axis]*=spec["axis_scale"][axis]
    normalize(obj,spec)
    geo=spec["geometry"]
    removed=cleanup(obj,spec["height_m"]*geo["merge_distance_ratio"])
    if geo["remesh"]=="voxel":
        lo,hi=bounds(obj)
        voxel=max(hi-lo)*geo["voxel_size_ratio"]
        mod=obj.modifiers.new("ClayFarmVoxel","REMESH")
        mod.mode="VOXEL"; mod.voxel_size=voxel; mod.use_remove_disconnected=False
        bpy.ops.object.modifier_apply(modifier=mod.name)
        if not obj.data.polygons: raise ValueError("Voxel remesh produced no surface")
    if geo["smooth_iterations"]:
        mod=obj.modifiers.new("ClayFarmSmooth","SMOOTH")
        mod.factor=.5; mod.iterations=geo["smooth_iterations"]
        bpy.ops.object.modifier_apply(modifier=mod.name)
    target=spec["target_triangles"]
    budget(obj,target)
    removed+=cleanup(obj,0)
    # Remesh/decimate/smooth can move bounds; enforce final size and pivot afterward.
    normalize(obj,spec)
    for p in obj.data.polygons: p.use_smooth=geo["shade_smooth"]
    # Do not automatically close holes: a cup's opening may be intentional.
    bm=bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    non_manifold=sum(not e.is_manifold for e in bm.edges)
    bm.to_mesh(obj.data); bm.free()
    if spec["material"]["mode"]=="clay_single":
        mat=bpy.data.materials.new("ClayFarmClay"); mat.use_nodes=True
        bsdf=mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value=spec["material"]["color"]
        bsdf.inputs["Roughness"].default_value=spec["material"]["roughness"]
        bsdf.inputs["Metallic"].default_value=0.0
        obj.data.materials.clear(); obj.data.materials.append(mat)
        for p in obj.data.polygons: p.material_index=0
    obj.data.update(); bpy.context.view_layer.update()
    lo,hi=bounds(obj); dims=hi-lo
    obj.data.calc_loop_triangles(); count=len(obj.data.loop_triangles)
    bm=bmesh.new(); bm.from_mesh(obj.data)
    connected=0; remaining=set(bm.verts)
    while remaining:
        stack=[remaining.pop()]; connected+=1
        while stack:
            v=stack.pop()
            for e in v.link_edges:
                other=e.other_vert(v)
                if other in remaining: remaining.remove(other); stack.append(other)
    bm.free()
    pivot_ok=abs((lo+hi).x)<1e-5 and abs((lo+hi).y)<1e-5 and abs(lo.z if spec["pivot"]=="bottom_center" else (lo+hi).z)<1e-5
    metrics={"triangles":count,"input_triangles":initial_triangles,"cleanup_removed_vertices":removed,"vertices":len(obj.data.vertices),"objects":1,"materials":len(obj.data.materials),
             "blender_version":bpy.app.version_string,"bounds_min":list(lo),"bounds_max":list(hi),"pivot_pass":pivot_ok,
             "dimensions_m":list(dims),"pivot":spec["pivot"],"non_manifold_edges":non_manifold,"connected_components":connected,
             "hard_pass":bool(pivot_ok and 0<count<=target and all(math.isfinite(x) and x>0 for x in dims) and abs(dims.z-spec["height_m"])<max(0.0001,spec["height_m"]*0.02)),
             "warnings":[]}
    if non_manifold: metrics["warnings"].append("non_manifold_edges_require_visual_review_not_automatic_rejection")
    if connected>1: metrics["warnings"].append("multiple_connected_components_require_visual_review")
    if spec["material"]["mode"]=="clay_single": metrics["warnings"].append("all_parts_intentionally_use_one_color")
    if geo["remesh"]=="voxel": metrics["warnings"].append("voxel_remesh_can_close_openings_or_remove_thin_parts_review_silhouette")
    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True); bpy.context.view_layer.objects.active=obj
    bpy.ops.export_scene.gltf(filepath=str(out/"mesh.glb"),export_format="GLB",use_selection=True,export_yup=True)
    bpy.ops.export_scene.fbx(filepath=str(out/"mesh.fbx"),use_selection=True,object_types={"MESH"},add_leaf_bones=False,
                             axis_forward="-Z",axis_up="Y",path_mode="COPY",embed_textures=True)
    metrics["extras"]=extras(obj,spec,out)
    if any(e["role"]=="lod" and e["triangles"]>e["target_triangles"] for e in metrics["extras"]): metrics["hard_pass"]=False
    write(out/"metrics.json",metrics)


def preview(params):
    obj=import_mesh(params["input"]); spec=params["spec"]
    lo,hi=bounds(obj); center=(lo+hi)/2; radius=max((hi-lo).length/2,0.01)
    view=params["view"]
    directions={"front":(0,-1,0),"right":(1,0,0),"back":(0,1,0),"three_quarter":(1,-1,0.7),"top":(0,0,1),"bottom":(0,0,-1)}
    direction=Vector(directions[view]).normalized()
    bpy.ops.object.camera_add(location=center+direction*radius*4)
    cam=bpy.context.object; cam.rotation_euler=(center-cam.location).to_track_quat("-Z","X" if view in ("top","bottom") else "Y").to_euler()
    cam.data.type="ORTHO"; cam.data.ortho_scale=radius*2.3; cam.data.clip_start=max(0.0001,radius/1000); cam.data.clip_end=radius*100
    scene=bpy.context.scene; scene.camera=cam
    for loc,power,size in [((2,-3,4),700,4),((-3,-1,2),350,4),((1,3,3),500,3)]:
        bpy.ops.object.light_add(type="AREA",location=center+Vector(loc)*radius)
        light=bpy.context.object; light.data.energy=power*radius*radius; light.data.shape="DISK"; light.data.size=size*radius
        light.rotation_euler=(center-light.location).to_track_quat("-Z","Y").to_euler()
    scene.world=bpy.data.worlds.new("ClayFarmWorld"); scene.world.use_nodes=True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value=(0.75,0.75,0.75,1)
    scene.world.node_tree.nodes["Background"].inputs[1].default_value=0.35
    scene.render.engine="CYCLES"; scene.cycles.device="CPU"; scene.cycles.samples=16
    scene.render.threads_mode="FIXED"; scene.render.threads=params.get("cpu_threads",2)
    scene.render.resolution_x=scene.render.resolution_y=spec["preview_size"]; scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG"; scene.render.image_settings.color_mode="RGBA"; scene.render.image_settings.color_depth="8"
    scene.render.film_transparent=True; scene.render.filepath=str(Path(params["output"])/"preview.png")
    bpy.ops.render.render(write_still=True)


if __name__=="__main__":
    args=sys.argv[sys.argv.index("--")+1:]
    params=json.loads(Path(args[0]).read_text(encoding="utf-8"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if params["kind"]=="process": process(params)
    elif params["kind"]=="preview": preview(params)
    else: raise ValueError("Unknown operation")
