using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace ClayFarm.Editor.Tests
{
    // Batch entry point for a disposable Unity project. No game project is required.
    public static class ClayFarmImportPolicyVerification
    {
        private const string Source = "Assets/PolicyFixtures/source.fbx";

        public static void Run()
        {
            string project = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
            if (!File.Exists(Path.Combine(project, ".clayfarm-policy-test-project")))
                throw new InvalidOperationException("Use a marked disposable test project.");

            string fixture = Environment.GetEnvironmentVariable("CLAYFARM_UNITY_FIXTURE");
            if (string.IsNullOrEmpty(fixture) || !File.Exists(fixture))
                throw new InvalidOperationException("Set CLAYFARM_UNITY_FIXTURE to the generated FBX.");

            Directory.CreateDirectory("Assets/PolicyFixtures");
            File.Copy(fixture, Source, true);
            AssetDatabase.ImportAsset(Source, ImportAssetOptions.ForceSynchronousImport);
            var source = (ModelImporter)AssetImporter.GetAtPath(Source);
            source.meshCompression = ModelImporterMeshCompression.Low;
            source.animationType = ModelImporterAnimationType.Generic;
            source.importBlendShapes = true;
            source.importAnimation = true;
            source.globalScale = 0.75f;
            source.isReadable = true;
            source.userData = "preserve-user-setting";
            source.SaveAndReimport();
            Verify(Source, false, false);

            var cases = new[]
            {
                ("Assets/ClayFarm/Models/animated.fbx", true, false),
                ("Assets/ClayFarm/StaticMeshes/prop.fbx", true, true),
                ("Assets/ClayFarm/StaticMeshes/Nested/prop.fbx", true, true),
                ("Assets/ClayFarm/StaticMeshesBackup/animated.fbx", true, false),
                ("Assets/ClayFarmOther/animated.fbx", false, false),
                ("Assets/clayfarm/staticmeshes/upper.FBX", true, true),
            };
            var passed = new List<string> { "outside-source: animation and blend shape fixture present" };
            foreach (var item in cases)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(item.Item1));
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                Check(AssetDatabase.CopyAsset(Source, item.Item1), "copy " + item.Item1);
                AssetDatabase.ImportAsset(item.Item1, ImportAssetOptions.ForceSynchronousImport
                    | ImportAssetOptions.ForceUpdate);
                Verify(item.Item1, item.Item2, item.Item3);
                passed.Add(item.Item1);
            }

            var forced = (ModelImporter)AssetImporter.GetAtPath(cases[0].Item1);
            forced.meshCompression = ModelImporterMeshCompression.Off;
            forced.importAnimation = false; // A separate clip file can animate this Generic rig.
            forced.SaveAndReimport();
            forced = (ModelImporter)AssetImporter.GetAtPath(cases[0].Item1);
            Check(forced.meshCompression == ModelImporterMeshCompression.Medium, "Medium on reimport");
            Check(!forced.importAnimation && forced.importBlendShapes
                && forced.animationType == ModelImporterAnimationType.Generic, "independent settings retained");
            passed.Add("reimport: Medium fixed; Generic rig retained with embedded clips disabled");

            File.WriteAllLines(Path.Combine(project, "policy-verification.txt"), passed);
            Debug.Log("CLAYFARM_IMPORT_POLICY_PASS " + passed.Count + " scenarios; Unity " + Application.unityVersion);
        }

        private static void Verify(string path, bool managed, bool unusedFeatures)
        {
            var importer = (ModelImporter)AssetImporter.GetAtPath(path);
            Check(importer.meshCompression == (managed
                ? ModelImporterMeshCompression.Medium : ModelImporterMeshCompression.Low), path + " compression");
            Check(importer.importBlendShapes == !unusedFeatures, path + " blend shapes setting");
            Check(importer.importAnimation == !unusedFeatures, path + " animation setting");
            Check(importer.animationType == (unusedFeatures
                ? ModelImporterAnimationType.None : ModelImporterAnimationType.Generic), path + " rig setting");
            Check(Math.Abs(importer.globalScale - 0.75f) < 0.0001f && importer.isReadable
                && importer.userData == "preserve-user-setting", path + " unrelated settings");
            UnityEngine.Object[] assets = AssetDatabase.LoadAllAssetsAtPath(path);
            Check(assets.OfType<Mesh>().Any(), path + " actual imported mesh");
            Check(assets.OfType<Mesh>().Any(mesh => mesh.blendShapeCount > 0) == !unusedFeatures,
                path + " actual blend shape data");
            Check(assets.OfType<AnimationClip>().Any(clip => !clip.name.StartsWith("__preview__"))
                == !unusedFeatures, path + " actual clip data");
        }

        private static void Check(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException("Import policy check failed: " + message);
        }
    }
}
