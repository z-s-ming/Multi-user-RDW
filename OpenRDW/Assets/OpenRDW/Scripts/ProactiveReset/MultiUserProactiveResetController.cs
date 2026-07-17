using System.Collections.Generic;
using UnityEngine;

public class MultiUserProactiveResetController : MonoBehaviour
{
    public enum Strategy
    {
        PassiveOnly,
        WorseningHighestRisk,
        WorseningCounterfactual
    }

    [HideInInspector]
    public Strategy strategy = Strategy.PassiveOnly;

    [HideInInspector]
    public float decisionDt = 0.5f;
    [HideInInspector]
    public float thetaW = 0.25f;
    [HideInInspector]
    public float thetaG = 0.5f;
    [HideInInspector]
    public float proactiveResetCooldown = 2.0f;
    [HideInInspector]
    public float velocityHistorySeconds = 1.0f;

    [HideInInspector]
    public float userRadius = 0.3f;
    [HideInInspector]
    public float safeBoundaryDistance = 0.8f;
    [HideInInspector]
    public float emergencyBoundaryDistance = 0.5f;
    [HideInInspector]
    public float safePairDistance = 1.0f;
    [HideInInspector]
    public float severePairDistance = 0.6f;
    [HideInInspector]
    public float boundaryWeight = 1.0f;
    [HideInInspector]
    public float pairwiseWeight = 1.0f;
    [HideInInspector]
    public float resetPressureWeight = 0.5f;

    [HideInInspector]
    public float predictionHorizon = 3.0f;
    [HideInInspector]
    public float predictionStep = 0.5f;
    [HideInInspector]
    public float resetDurationForPrediction = 1.2f;
    [HideInInspector]
    public bool requirePositiveCounterfactualBenefit = true;
    [HideInInspector]
    public float interruptCostWeight = 0f;

    [Header("Debug")]
    public float lastGroupRisk;
    public float lastWorsening;
    public float lastPeakRisk;
    public int lastSelectedUserId = -1;
    public string lastSelectionReason = "";

    private struct PositionSample
    {
        public float Time;
        public Vector2 Position;
    }

    private GlobalConfiguration globalConfiguration;
    private readonly Dictionary<int, Queue<PositionSample>> positionHistoryByUser = new Dictionary<int, Queue<PositionSample>>();
    private readonly Dictionary<int, float> lastProactiveResetTimeByUser = new Dictionary<int, float>();
    private readonly MultiUserProactiveResetLogger logger = new MultiUserProactiveResetLogger();
    private float lastDecisionTime = float.NegativeInfinity;

    private void Awake()
    {
        globalConfiguration = GetComponent<GlobalConfiguration>();
    }

    public void ResetDecisionState()
    {
        positionHistoryByUser.Clear();
        lastProactiveResetTimeByUser.Clear();
        lastDecisionTime = float.NegativeInfinity;
        lastGroupRisk = 0f;
        lastWorsening = 0f;
        lastPeakRisk = 0f;
        lastSelectedUserId = -1;
        lastSelectionReason = "";
    }

    public void BeginExperimentLogging(int trialId, ExperimentSetup setup)
    {
        logger.BeginTrial(globalConfiguration, trialId, setup);
    }

    public void EndExperimentLogging()
    {
        logger.EndTrial();
    }

    public void LogResetEvent(float time, int userId, string source, bool accepted, string reason)
    {
        logger.LogResetEvent(time, userId, source, accepted, reason);
    }

    public void TickDecision()
    {
        if (globalConfiguration == null || !globalConfiguration.experimentInProgress)
            return;

        float now = globalConfiguration.GetTime();
        UpdatePositionHistory(now);

        if (float.IsNegativeInfinity(lastDecisionTime))
            lastDecisionTime = now;

        if (now - lastDecisionTime < decisionDt)
            return;

        lastDecisionTime = now;

        if (strategy == Strategy.PassiveOnly)
        {
            List<MultiUserRiskWorseningModel.UserSnapshot> passiveUsers = BuildUserSnapshots(now);
            var passiveModel = BuildRiskModel();
            MultiUserRiskWorseningModel.RiskSnapshot passiveCurrent = passiveModel.EvaluateCurrent(passiveUsers);
            List<int> passiveEligibleUserIds = GetEligibleUserIds(passiveUsers, now);

            lastGroupRisk = passiveCurrent.GroupRisk;
            lastWorsening = float.NaN;
            lastPeakRisk = float.NaN;
            lastSelectedUserId = -1;
            lastSelectionReason = "passive_only";

            logger.LogUserSamples(now, passiveUsers, passiveCurrent.IndividualRisks, passiveEligibleUserIds);
            logger.LogDecision(now, strategy, passiveCurrent.GroupRisk, float.NaN, float.NaN, false, -1, lastSelectionReason, passiveEligibleUserIds, passiveCurrent.IndividualRisks);
            return;
        }

        if (!HasEnoughVelocityHistory(now))
        {
            lastSelectionReason = "insufficient_velocity_history";
            logger.LogDecision(now, strategy, float.NaN, float.NaN, float.NaN, false, -1, lastSelectionReason, null, null);
            return;
        }

        List<MultiUserRiskWorseningModel.UserSnapshot> users = BuildUserSnapshots(now);
        var model = BuildRiskModel();
        MultiUserRiskWorseningModel.RiskSnapshot current = model.EvaluateCurrent(users);
        MultiUserRiskWorseningModel.PredictionSnapshot prediction = model.PredictWorsening(users);
        List<int> eligibleUserIds = GetEligibleUserIds(users, now);
        logger.LogUserSamples(now, users, current.IndividualRisks, eligibleUserIds);

        lastGroupRisk = current.GroupRisk;
        lastWorsening = prediction.Worsening;
        lastPeakRisk = prediction.PeakRisk;
        lastSelectedUserId = -1;

        if (current.Emergency)
        {
            lastSelectionReason = "emergency_active";
            logger.LogDecision(now, strategy, current.GroupRisk, prediction.Worsening, prediction.PeakRisk, false, -1, lastSelectionReason, eligibleUserIds, current.IndividualRisks);
            return;
        }

        if (AnyUserResetting())
        {
            lastSelectionReason = "reset_active";
            logger.LogDecision(now, strategy, current.GroupRisk, prediction.Worsening, prediction.PeakRisk, false, -1, lastSelectionReason, eligibleUserIds, current.IndividualRisks);
            return;
        }

        if (prediction.Worsening <= thetaW || prediction.PeakRisk <= thetaG)
        {
            lastSelectionReason = "no_trigger";
            logger.LogDecision(now, strategy, current.GroupRisk, prediction.Worsening, prediction.PeakRisk, false, -1, lastSelectionReason, eligibleUserIds, current.IndividualRisks);
            return;
        }

        int selectedUserId = SelectUser(model, users, current, prediction, now);
        if (selectedUserId < 0)
        {
            lastSelectionReason = "no_eligible_user";
            logger.LogDecision(now, strategy, current.GroupRisk, prediction.Worsening, prediction.PeakRisk, true, -1, lastSelectionReason, eligibleUserIds, current.IndividualRisks);
            return;
        }

        RedirectionManager selected = GetRedirectionManager(selectedUserId);
        if (selected != null && selected.RequestProactiveReset())
        {
            lastProactiveResetTimeByUser[selectedUserId] = now;
            lastSelectedUserId = selectedUserId;
            lastSelectionReason = strategy == Strategy.WorseningHighestRisk
                ? "highest_current_risk"
                : "counterfactual_worsening_reduction";
            logger.LogDecision(now, strategy, current.GroupRisk, prediction.Worsening, prediction.PeakRisk, true, selectedUserId, lastSelectionReason, eligibleUserIds, current.IndividualRisks);
        }
        else
        {
            lastSelectionReason = "reset_request_rejected";
            logger.LogDecision(now, strategy, current.GroupRisk, prediction.Worsening, prediction.PeakRisk, true, selectedUserId, lastSelectionReason, eligibleUserIds, current.IndividualRisks);
            logger.LogResetEvent(now, selectedUserId, "proactive", false, lastSelectionReason);
        }
    }

    private MultiUserRiskWorseningModel BuildRiskModel()
    {
        var settings = new MultiUserRiskWorseningModel.Settings
        {
            userRadius = userRadius,
            safeBoundaryDistance = safeBoundaryDistance,
            emergencyBoundaryDistance = emergencyBoundaryDistance,
            safePairDistance = safePairDistance,
            severePairDistance = severePairDistance,
            boundaryWeight = boundaryWeight,
            pairwiseWeight = pairwiseWeight,
            resetPressureWeight = resetPressureWeight,
            predictionHorizon = predictionHorizon,
            predictionStep = predictionStep,
            resetDurationForPrediction = resetDurationForPrediction
        };

        return new MultiUserRiskWorseningModel(
            settings,
            globalConfiguration.trackingSpacePoints,
            globalConfiguration.obstaclePolygons);
    }

    private int SelectUser(
        MultiUserRiskWorseningModel model,
        List<MultiUserRiskWorseningModel.UserSnapshot> users,
        MultiUserRiskWorseningModel.RiskSnapshot current,
        MultiUserRiskWorseningModel.PredictionSnapshot noResetPrediction,
        float now)
    {
        if (strategy == Strategy.WorseningCounterfactual)
            return SelectCounterfactualUser(model, users, current, noResetPrediction, now);

        return SelectHighestCurrentRiskUser(users, current, now);
    }

    private int SelectHighestCurrentRiskUser(
        List<MultiUserRiskWorseningModel.UserSnapshot> users,
        MultiUserRiskWorseningModel.RiskSnapshot current,
        float now)
    {
        int selectedUserId = -1;
        float selectedRisk = float.MinValue;

        for (int i = 0; i < users.Count; i++)
        {
            int userId = users[i].UserId;
            if (!IsEligibleForProactiveReset(userId, now))
                continue;

            float risk = current.IndividualRisks[i];
            if (risk > selectedRisk)
            {
                selectedRisk = risk;
                selectedUserId = userId;
            }
        }

        return selectedUserId;
    }

    private int SelectCounterfactualUser(
        MultiUserRiskWorseningModel model,
        List<MultiUserRiskWorseningModel.UserSnapshot> users,
        MultiUserRiskWorseningModel.RiskSnapshot current,
        MultiUserRiskWorseningModel.PredictionSnapshot noResetPrediction,
        float now)
    {
        int selectedUserId = -1;
        float selectedScore = float.MinValue;

        for (int i = 0; i < users.Count; i++)
        {
            int userId = users[i].UserId;
            if (!IsEligibleForProactiveReset(userId, now))
                continue;

            MultiUserRiskWorseningModel.PredictionSnapshot resetPrediction = model.PredictWorsening(users, userId);
            float benefit = noResetPrediction.Worsening - resetPrediction.Worsening;
            float score = benefit - interruptCostWeight * GetInterruptCost(userId, current.IndividualRisks[i]);

            if (score > selectedScore)
            {
                selectedScore = score;
                selectedUserId = userId;
            }
        }

        if (requirePositiveCounterfactualBenefit && selectedScore <= 0f)
            return -1;

        return selectedUserId;
    }

    private float GetInterruptCost(int userId, float currentRisk)
    {
        RedirectionManager rm = GetRedirectionManager(userId);
        if (rm == null)
            return 0f;

        float speed = rm.deltaPos.magnitude / Mathf.Max(globalConfiguration.GetDeltaTime(), 0.0001f);
        float recentlyReset = IsInProactiveCooldown(userId, globalConfiguration.GetTime()) ? 1f : 0f;
        return recentlyReset + speed + currentRisk * 0f;
    }

    private void UpdatePositionHistory(float now)
    {
        for (int i = 0; i < globalConfiguration.redirectedAvatars.Count; i++)
        {
            RedirectionManager rm = globalConfiguration.redirectedAvatars[i].GetComponent<RedirectionManager>();
            int userId = rm.movementManager.avatarId;
            Queue<PositionSample> history;
            if (!positionHistoryByUser.TryGetValue(userId, out history))
            {
                history = new Queue<PositionSample>();
                positionHistoryByUser[userId] = history;
            }

            history.Enqueue(new PositionSample
            {
                Time = now,
                Position = Utilities.FlattenedPos2D(rm.currPosReal)
            });

            while (history.Count > 0 && now - history.Peek().Time > velocityHistorySeconds)
                history.Dequeue();
        }
    }

    private bool HasEnoughVelocityHistory(float now)
    {
        for (int i = 0; i < globalConfiguration.redirectedAvatars.Count; i++)
        {
            RedirectionManager rm = globalConfiguration.redirectedAvatars[i].GetComponent<RedirectionManager>();
            Queue<PositionSample> history;
            if (!positionHistoryByUser.TryGetValue(rm.movementManager.avatarId, out history) || history.Count < 2)
                return false;

            if (now - history.Peek().Time < velocityHistorySeconds * 0.75f)
                return false;
        }

        return true;
    }

    private List<MultiUserRiskWorseningModel.UserSnapshot> BuildUserSnapshots(float now)
    {
        var users = new List<MultiUserRiskWorseningModel.UserSnapshot>();
        for (int i = 0; i < globalConfiguration.redirectedAvatars.Count; i++)
        {
            RedirectionManager rm = globalConfiguration.redirectedAvatars[i].GetComponent<RedirectionManager>();
            int userId = rm.movementManager.avatarId;
            users.Add(new MultiUserRiskWorseningModel.UserSnapshot
            {
                UserId = userId,
                Position = Utilities.FlattenedPos2D(rm.currPosReal),
                Velocity = GetRecentVelocity(userId, now),
                IsResetting = rm.inReset
            });
        }
        return users;
    }

    private Vector2 GetRecentVelocity(int userId, float now)
    {
        Queue<PositionSample> history;
        if (!positionHistoryByUser.TryGetValue(userId, out history) || history.Count < 2)
            return Vector2.zero;

        PositionSample first = history.Peek();
        PositionSample last = first;
        foreach (PositionSample sample in history)
        {
            last = sample;
        }

        float dt = Mathf.Max(last.Time - first.Time, 0.0001f);
        return (last.Position - first.Position) / dt;
    }

    private bool AnyUserResetting()
    {
        for (int i = 0; i < globalConfiguration.redirectedAvatars.Count; i++)
        {
            RedirectionManager rm = globalConfiguration.redirectedAvatars[i].GetComponent<RedirectionManager>();
            if (rm.inReset)
                return true;
        }
        return false;
    }

    private bool IsEligibleForProactiveReset(int userId, float now)
    {
        RedirectionManager rm = GetRedirectionManager(userId);
        if (rm == null || rm.inReset || rm.ifJustEndReset || rm.movementManager.ifInvalid)
            return false;

        if (rm.resetter == null || rm.resetter is NullResetter)
            return false;

        return !IsInProactiveCooldown(userId, now);
    }

    private bool IsInProactiveCooldown(int userId, float now)
    {
        float lastResetTime;
        return lastProactiveResetTimeByUser.TryGetValue(userId, out lastResetTime) &&
               now - lastResetTime < proactiveResetCooldown;
    }

    private List<int> GetEligibleUserIds(List<MultiUserRiskWorseningModel.UserSnapshot> users, float now)
    {
        var eligibleUserIds = new List<int>();
        for (int i = 0; i < users.Count; i++)
        {
            if (IsEligibleForProactiveReset(users[i].UserId, now))
                eligibleUserIds.Add(users[i].UserId);
        }

        return eligibleUserIds;
    }

    private RedirectionManager GetRedirectionManager(int userId)
    {
        for (int i = 0; i < globalConfiguration.redirectedAvatars.Count; i++)
        {
            RedirectionManager rm = globalConfiguration.redirectedAvatars[i].GetComponent<RedirectionManager>();
            if (rm.movementManager.avatarId == userId)
                return rm;
        }

        return null;
    }
}
