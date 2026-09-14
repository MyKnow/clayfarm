using System;
using UnityEditor;

namespace ClayFarm.Editor
{
    // Install under an Editor folder. Folder membership declares intended data use;
    // it does not describe whether the GameObject moves at runtime.
    public sealed class ClayFarmModelImportPolicy : AssetPostprocessor
    {
        private const string Root = "Assets/ClayFarm/";
        private const string StaticMeshes = Root + "StaticMeshes/";

        public override uint GetVersion() => 1;

        private void OnPreprocessModel()
        {
            if (!(assetImporter is ModelImporter importer)
                || !assetPath.StartsWith(Root, StringComparison.OrdinalIgnoreCase)
                || !assetPath.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase))
                return;

            importer.meshCompression = ModelImporterMeshCompression.Medium;

            // Unclassified/animated models retain their individual import choices.
            if (!assetPath.StartsWith(StaticMeshes, StringComparison.OrdinalIgnoreCase))
                return;

            importer.importBlendShapes = false;
            importer.animationType = ModelImporterAnimationType.None;
            importer.importAnimation = false;
        }
    }
}
