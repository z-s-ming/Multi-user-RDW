using System.Collections.Generic;
using UnityEngine;

public class MultiUserRiskWorseningModel
{
    public class Settings
    {
        public float userRadius = 0.3f;
        public float safeBoundaryDistance = 0.8f;
        public float emergencyBoundaryDistance = 0.5f;
        public float safePairDistance = 1.0f;
        public float severePairDistance = 0.6f;
        public float boundaryWeight = 1.0f;
        public float pairwiseWeight = 1.0f;
        public float resetPressureWeight = 0.5f;
        public float predictionHorizon = 3.0f;
        public float predictionStep = 0.5f;
        public float resetDurationForPrediction = 1.2f;
    }

    public struct UserSnapshot
    {
        public int UserId;
        public Vector2 Position;
        public Vector2 Velocity;
        public bool IsResetting;
    }

    public struct RiskSnapshot
    {
        public float GroupRisk;
        public float MaxIndividualRisk;
        public int MaxIndividualRiskUserId;
        public float MinBoundaryDistance;
        public float MinPairwiseDistance;
        public bool Emergency;
        public float[] IndividualRisks;
    }

    public struct PredictionSnapshot
    {
        public float Worsening;
        public float PeakRisk;
    }

    private readonly Settings settings;
    private readonly List<Vector2> trackingSpacePoints;
    private readonly List<List<Vector2>> obstaclePolygons;

    public MultiUserRiskWorseningModel(Settings settings, List<Vector2> trackingSpacePoints, List<List<Vector2>> obstaclePolygons)
    {
        this.settings = settings;
        this.trackingSpacePoints = trackingSpacePoints;
        this.obstaclePolygons = obstaclePolygons;
    }

    public RiskSnapshot EvaluateCurrent(IList<UserSnapshot> users)
    {
        return Evaluate(users);
    }

    public PredictionSnapshot PredictWorsening(IList<UserSnapshot> users)
    {
        return PredictWorsening(users, -1);
    }

    public PredictionSnapshot PredictWorsening(IList<UserSnapshot> users, int resetCandidateUserId)
    {
        RiskSnapshot current = Evaluate(users);
        float worsening = 0f;
        float peakRisk = current.GroupRisk;

        for (float tau = settings.predictionStep; tau <= settings.predictionHorizon + 0.0001f; tau += settings.predictionStep)
        {
            List<UserSnapshot> predicted = PredictUsers(users, tau, resetCandidateUserId);
            RiskSnapshot future = Evaluate(predicted);
            worsening += Mathf.Max(0f, future.GroupRisk - current.GroupRisk);
            peakRisk = Mathf.Max(peakRisk, future.GroupRisk);
        }

        return new PredictionSnapshot
        {
            Worsening = worsening,
            PeakRisk = peakRisk
        };
    }

    private List<UserSnapshot> PredictUsers(IList<UserSnapshot> users, float tau, int resetCandidateUserId)
    {
        var predicted = new List<UserSnapshot>(users.Count);
        for (int i = 0; i < users.Count; i++)
        {
            UserSnapshot user = users[i];
            Vector2 velocity = user.Velocity;

            if (user.UserId == resetCandidateUserId)
            {
                float activeTime = Mathf.Max(0f, tau - settings.resetDurationForPrediction);
                user.Position += velocity * activeTime;
                user.IsResetting = tau <= settings.resetDurationForPrediction;
            }
            else
            {
                user.Position += velocity * tau;
            }

            predicted.Add(user);
        }
        return predicted;
    }

    private RiskSnapshot Evaluate(IList<UserSnapshot> users)
    {
        int userCount = users.Count;
        float boundarySum = 0f;
        float pairwiseSum = 0f;
        int pairCount = 0;
        float resetPressureSum = 0f;
        float minBoundaryDistance = float.MaxValue;
        float minPairwiseDistance = float.MaxValue;
        bool emergency = false;
        var individualRisks = new float[userCount];
        int maxIndividualRiskUserId = -1;
        float maxIndividualRisk = float.MinValue;

        for (int i = 0; i < userCount; i++)
        {
            float boundaryDistance = GetBoundaryDistance(users[i].Position);
            minBoundaryDistance = Mathf.Min(minBoundaryDistance, boundaryDistance);
            float boundaryRisk = HingeDistance(boundaryDistance, settings.safeBoundaryDistance);
            float pairRisk = 0f;
            float nearestPairDistance = float.MaxValue;

            for (int j = 0; j < userCount; j++)
            {
                if (i == j)
                    continue;

                float pairDistance = GetPairDistance(users[i].Position, users[j].Position);
                nearestPairDistance = Mathf.Min(nearestPairDistance, pairDistance);
                pairRisk = Mathf.Max(pairRisk, HingeDistance(pairDistance, settings.safePairDistance));
            }

            bool userEmergency =
                boundaryDistance < settings.emergencyBoundaryDistance ||
                nearestPairDistance < settings.severePairDistance;
            float resetPressure = userEmergency || users[i].IsResetting ? 1f : 0f;
            float individualRisk =
                settings.boundaryWeight * boundaryRisk +
                settings.pairwiseWeight * pairRisk +
                settings.resetPressureWeight * resetPressure;

            individualRisks[i] = individualRisk;
            if (individualRisk > maxIndividualRisk)
            {
                maxIndividualRisk = individualRisk;
                maxIndividualRiskUserId = users[i].UserId;
            }

            boundarySum += boundaryRisk;
            resetPressureSum += resetPressure;
            emergency = emergency || userEmergency;
        }

        for (int i = 0; i < userCount; i++)
        {
            for (int j = i + 1; j < userCount; j++)
            {
                float pairDistance = GetPairDistance(users[i].Position, users[j].Position);
                minPairwiseDistance = Mathf.Min(minPairwiseDistance, pairDistance);
                pairwiseSum += HingeDistance(pairDistance, settings.safePairDistance);
                pairCount++;
            }
        }

        if (float.IsPositiveInfinity(minPairwiseDistance) || minPairwiseDistance == float.MaxValue)
            minPairwiseDistance = 0f;

        float boundaryRiskMean = userCount > 0 ? boundarySum / userCount : 0f;
        float pairwiseRiskMean = pairCount > 0 ? pairwiseSum / pairCount : 0f;
        float resetPressureMean = userCount > 0 ? resetPressureSum / userCount : 0f;

        return new RiskSnapshot
        {
            GroupRisk =
                settings.boundaryWeight * boundaryRiskMean +
                settings.pairwiseWeight * pairwiseRiskMean +
                settings.resetPressureWeight * resetPressureMean,
            MaxIndividualRisk = maxIndividualRisk,
            MaxIndividualRiskUserId = maxIndividualRiskUserId,
            MinBoundaryDistance = minBoundaryDistance == float.MaxValue ? 0f : minBoundaryDistance,
            MinPairwiseDistance = minPairwiseDistance,
            Emergency = emergency,
            IndividualRisks = individualRisks
        };
    }

    private float GetBoundaryDistance(Vector2 position)
    {
        float nearest = GetNearestDistanceToPolygon(position, trackingSpacePoints);
        if (obstaclePolygons != null)
        {
            for (int i = 0; i < obstaclePolygons.Count; i++)
            {
                nearest = Mathf.Min(nearest, GetNearestDistanceToPolygon(position, obstaclePolygons[i]));
            }
        }
        return nearest;
    }

    private float GetPairDistance(Vector2 a, Vector2 b)
    {
        return (a - b).magnitude - 2f * settings.userRadius;
    }

    private float HingeDistance(float distance, float safeDistance)
    {
        if (safeDistance <= 0f)
            return 0f;

        return Mathf.Max(0f, (safeDistance - distance) / safeDistance);
    }

    private float GetNearestDistanceToPolygon(Vector2 position, List<Vector2> polygon)
    {
        if (polygon == null || polygon.Count == 0)
            return float.MaxValue;

        float nearest = float.MaxValue;
        for (int i = 0; i < polygon.Count; i++)
        {
            Vector2 a = polygon[i];
            Vector2 b = polygon[(i + 1) % polygon.Count];
            Vector2 nearestPoint = GetNearestPointOnSegment(position, a, b);
            nearest = Mathf.Min(nearest, (position - nearestPoint).magnitude);
        }
        return nearest;
    }

    private Vector2 GetNearestPointOnSegment(Vector2 point, Vector2 a, Vector2 b)
    {
        Vector2 ab = b - a;
        float abSqrMagnitude = ab.sqrMagnitude;
        if (abSqrMagnitude <= 0.000001f)
            return a;

        float t = Vector2.Dot(point - a, ab) / abSqrMagnitude;
        t = Mathf.Clamp01(t);
        return a + ab * t;
    }
}
