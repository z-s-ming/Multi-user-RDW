using UnityEngine;
using System.Collections.Generic;

// ARC Resetter: ported/adapted from resetter.cpp / reset_to_forward_distance.cpp
// Chooses a physical direction to match virtual free space and performs a full 360 spin reset.
public class ARC_Resetter : Resetter
{
    [SerializeField]
    private int sampleRate = 20;

    private List<float> sampleDirections = new List<float>(); // radians

    private float overallInjectedRotation = 0f;
    private float requiredRotateAngle = 0f; // degrees for simulated walker
    private int rotateDir = 1; // 1 clockwise, -1 counter-clockwise
    private bool searchingPhase = false; // whether we're rotating to search for best direction
    private float searchedRotation = 0f; // accumulated rotation during search (degrees)
    private float virtDistNorth = 0f;
    private float bestLossSoFar = float.MaxValue;
    private Vector2 bestDirSoFar = Vector2.zero;

    void Start()
    {
        sampleDirections.Clear();
        for (int i = 0; i < sampleRate; i++)
        {
            sampleDirections.Add(((2f * Mathf.PI) / sampleRate) * i);
        }
    }

    public override bool IsResetRequired()
    {
        return IfCollisionHappens();
    }

    public override void InitializeReset()
    {
        // choose best direction then initialize a 360-degree spin reset
        var rm = redirectionManager;

        Vector2 physPos = Utilities.FlattenedPos2D(rm.currPosReal);
        Vector2 virtPos = Utilities.FlattenedPos2D(rm.currPos);

        // virtual heading
        Vector2 virtHeading = Utilities.FlattenedDir2D(rm.currDir);

        // 暂时为空
        //var trackingSpacePoints = rm.globalConfiguration.trackingSpacePoints;
        //var obstaclePolygons = rm.globalConfiguration.obstaclePolygons;
        var trackingSpacePoints = new List<Vector2>();
        var obstaclePolygons = new List<List<Vector2>>();

        // compute virtual distance in heading direction using virtual tracking space
        virtDistNorth = DistanceInDirection(virtPos, virtHeading, trackingSpacePoints, obstaclePolygons);

        float bestLoss = float.MaxValue;
        Vector2 bestDir = Vector2.zero;
        float bestUnderLoss = float.MaxValue;
        Vector2 bestUnderDir = Vector2.zero;

        // compute approximate closest wall normal (from nearest edge)
        Vector2 closestWallNormal = ComputeClosestWallNormal(physPos, trackingSpacePoints, obstaclePolygons);

        foreach (var d in sampleDirections)
        {
            var dir = new Vector2(Mathf.Cos(d), Mathf.Sin(d));

            // ensure we face away from wall after resetting
            if (Vector2.Dot(dir, closestWallNormal) < Utilities.eps) continue;

            float physDistNorth = DistanceInDirection(physPos, dir, trackingSpacePoints, obstaclePolygons);

            float lossNorth = physDistNorth - virtDistNorth;
            float sum = Mathf.Abs(lossNorth);

            if (sum < bestLoss)
            {
                bestLoss = sum;
                bestDir = dir;
            }

            if (physDistNorth < virtDistNorth)
            {
                if (sum < bestUnderLoss)
                {
                    bestUnderLoss = sum;
                    bestUnderDir = dir;
                }
            }
            else
            {
                if (sum < bestLoss)
                {
                    bestLoss = sum;
                    bestDir = dir;
                }
            }
        }

        if (bestLoss == float.MaxValue)
        {
            bestDir = bestUnderDir;
        }

        // Compute rotation needed: orient physical heading to bestDir by performing a full 360 virtual spin
        Vector2 physHeading = Utilities.FlattenedDir2D(rm.currDirReal);
        float angleToTarget = Vector2SignedAngle(physHeading, bestDir); // degrees, positive clockwise
        float complementAngle = 360f - Mathf.Abs(angleToTarget);
        complementAngle *= -Mathf.Sign(angleToTarget);

        float rotaGain = Mathf.Abs(complementAngle) / 360f; // not used directly here but kept for completeness

        // enter searching phase: rotate physical plane incrementally to sample directions
        overallInjectedRotation = 0f;
        searchedRotation = 0f;
        searchingPhase = true;
        bestLossSoFar = float.MaxValue;
        bestDirSoFar = bestDir;
        // HUD shows rotation direction during search (use complementAngle sign)
        rotateDir = complementAngle > 0 ? 1 : -1;
        SetHUD(rotateDir);
    }

    public override void InjectResetting()
    {
        var delta = redirectionManager.deltaDir;

        if (searchingPhase)
        {
            // Active search: rotate by a small step based on configured rotation speed
            float step = redirectionManager.GetDeltaTime() * redirectionManager.globalConfiguration.rotationSpeed * rotateDir;
            InjectRotation(step);
            searchedRotation += Mathf.Abs(step);
            overallInjectedRotation += Mathf.Abs(step);

            // Sample current physical heading as a candidate direction
            Vector2 physHeading = Utilities.FlattenedDir2D(redirectionManager.currDirReal);
            float physDistNorth = DistanceInDirection(Utilities.FlattenedPos2D(redirectionManager.currPosReal), physHeading, redirectionManager.globalConfiguration.trackingSpacePoints, redirectionManager.globalConfiguration.obstaclePolygons);
            float lossNorth = physDistNorth - virtDistNorth;
            float sum = Mathf.Abs(lossNorth);
            if (sum < bestLossSoFar)
            {
                bestLossSoFar = sum;
                bestDirSoFar = physHeading;
            }

            // finish searching after roughly a full sweep
            if (searchedRotation >= 360f - 1f)
            {
                searchingPhase = false;
                // after search, set up simulated walker rotation (full 360)
                requiredRotateAngle = 360f;
                // determine rotateDir based on angle between current phys heading and bestDirSoFar
                var currPhys = Utilities.FlattenedDir2D(redirectionManager.currDirReal);
                float angleToTarget = Vector2SignedAngle(currPhys, bestDirSoFar);
                rotateDir = angleToTarget > 0 ? 1 : -1;
                // show HUD for the simulated walker rotation
                SetHUD(rotateDir);
            }

            return;
        }

        // Execution phase: perform simulated walker rotation while optionally injecting physical rotations to assist
        if (Mathf.Abs(overallInjectedRotation) < 360f)
        {
            // perform rotation step based on rotation speed
            float step = redirectionManager.GetDeltaTime() * redirectionManager.globalConfiguration.rotationSpeed * rotateDir;
            float remaining = 360f - Mathf.Abs(overallInjectedRotation);
            if (Mathf.Abs(step) >= remaining || requiredRotateAngle == 0)
            {
                // finish
                InjectRotation(rotateDir * remaining);
                overallInjectedRotation += remaining * Mathf.Sign(rotateDir);
                redirectionManager.OnResetEnd();
            }
            else
            {
                InjectRotation(step);
                overallInjectedRotation += Mathf.Abs(step);
            }
        }
    }

    public override void EndReset()
    {
        DestroyHUD();
    }

    public override void SimulatedWalkerUpdate()
    {
        var rotateAngle = redirectionManager.GetDeltaTime() * redirectionManager.globalConfiguration.rotationSpeed;

        if (rotateAngle >= requiredRotateAngle)
        {
            rotateAngle = requiredRotateAngle;
            requiredRotateAngle = 0f;
        }
        else
        {
            requiredRotateAngle -= rotateAngle;
        }
        redirectionManager.simulatedWalker.RotateInPlace(rotateAngle * rotateDir);
    }

    // Helper: signed angle from a to b in degrees, positive means clockwise to match Utilities.GetSignedAngle convention
    private float Vector2SignedAngle(Vector2 a, Vector2 b)
    {
        var cross = Utilities.Cross(a, b);
        var ang = Vector2.Angle(a, b);
        return Mathf.Sign(cross) * ang;
    }

    // Compute distance from p along dir to the nearest intersection with polygon boundaries (tracking space + obstacles)
    private float DistanceInDirection(Vector2 p, Vector2 dir, List<Vector2> trackingSpace, List<List<Vector2>> obstacles)
    {
        dir.Normalize();
        float minT = float.MaxValue;

        if (trackingSpace != null && trackingSpace.Count >= 2)
        {
            float t = RaySegmentIntersectionMinT(p, dir, trackingSpace);
            if (t > 0) minT = Mathf.Min(minT, t);
        }

        if (obstacles != null)
        {
            foreach (var obs in obstacles)
            {
                if (obs == null || obs.Count < 2) continue;
                float t = RaySegmentIntersectionMinT(p, dir, obs);
                if (t > 0) minT = Mathf.Min(minT, t);
            }
        }

        if (minT == float.MaxValue) return 1000f;
        return minT;
    }

    // for a polygon (list of vertices), return min positive t where p + t*dir intersects an edge; return -1 if none
    private float RaySegmentIntersectionMinT(Vector2 p, Vector2 dir, List<Vector2> polygon)
    {
        float minT = float.MaxValue;
        for (int i = 0; i < polygon.Count; i++)
        {
            var a = polygon[i];
            var b = polygon[(i + 1) % polygon.Count];
            var v = b - a; // segment vector

            float denom = Utilities.Cross(dir, v);
            if (Mathf.Abs(denom) < 1e-6f) continue; // parallel

            // Solve p + t*dir = a + u*v => t = Cross(a - p, v) / Cross(dir, v)
            float t = Utilities.Cross(a - p, v) / denom;
            float u = Utilities.Cross(a - p, dir) / denom;
            if (t >= 0 && u >= 0f && u <= 1f)
            {
                if (t < minT) minT = t;
            }
        }
        if (minT == float.MaxValue) return -1f;
        return minT;
    }

    // Compute an approximate normal of the closest wall (edge) to position p
    private Vector2 ComputeClosestWallNormal(Vector2 p, List<Vector2> trackingSpace, List<List<Vector2>> obstacles)
    {
        float minDist = float.MaxValue;
        Vector2 bestNormal = Vector2.up; // default

        if (trackingSpace != null)
        {
            for (int i = 0; i < trackingSpace.Count; i++)
            {
                var a = trackingSpace[i];
                var b = trackingSpace[(i + 1) % trackingSpace.Count];
                var perp = ClosestPointOnSegment(p, a, b);
                float d = (p - perp).magnitude;
                if (d < minDist)
                {
                    minDist = d;
                    var e = (b - a).normalized;
                    bestNormal = new Vector2(e.y, -e.x).normalized; // rotate edge vector 90 degrees
                }
            }
        }

        if (obstacles != null)
        {
            foreach (var obs in obstacles)
            {
                for (int i = 0; i < obs.Count; i++)
                {
                    var a = obs[i];
                    var b = obs[(i + 1) % obs.Count];
                    var perp = ClosestPointOnSegment(p, a, b);
                    float d = (p - perp).magnitude;
                    if (d < minDist)
                    {
                        minDist = d;
                        var e = (b - a).normalized;
                        bestNormal = new Vector2(e.y, -e.x).normalized;
                    }
                }
            }
        }

        return bestNormal;
    }

    private Vector2 ClosestPointOnSegment(Vector2 p, Vector2 a, Vector2 b)
    {
        var ab = b - a;
        float t = Vector2.Dot(p - a, ab) / Vector2.Dot(ab, ab);
        t = Mathf.Clamp01(t);
        return a + t * ab;
    }
}
