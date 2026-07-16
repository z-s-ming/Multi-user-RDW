//
//

using UnityEngine;
using System.Collections;
using System.Collections.Generic;
using System;


public class ARC_Redirector : Redirector
{

    float REDIRECTION_LOSS_THRESHOLD = 0.1f; // Alignment threshold for when to turn off redirection.
    //float ROTA_GAIN_SMOOTHING = 0.125f; // Smoothing parameter for interpoating rotation gains between frames.

    // 初始化当前损失值，不清楚为什么初始是-1
    float prev_loss = -1.0f;
    float cur_loss = -1.0f;

    // 三个方向的当前损失值
    float cur_north_loss = 0.0f;
    float cur_east_loss = 0.0f;
    float cur_west_loss = 0.0f;

    float DistanceNorthRate = 1.0f;

    public override void InjectRedirection()
    {
        
        updateLosses();
        setGain();

        // 执行一次后更新loss值
        prev_loss = cur_loss;

    }

    public void updateLosses()
    {
        List<List<Vector2>> obstaclePolygons = redirectionManager.globalConfiguration.obstaclePolygons;
        List<Vector2> trackingSpacePoints = redirectionManager.globalConfiguration.trackingSpacePoints;
        List<Transform>  userTransforms = redirectionManager.globalConfiguration.GetAvatarTransforms();

        // 物理场景中Lossers的更新
         Vector2 phys_heading = Utilities.FlattenedDir2D(redirectionManager.currDirReal);
        List<Vector2> directions = new List<Vector2>
        {
            phys_heading,                               // Forward (north)
            new Vector2(phys_heading.y, -phys_heading.x), // Right (east)
            new Vector2(-phys_heading.y, phys_heading.x)  // Left (west)
        };

        // use positions (2D) as ray origins
        Vector2 physOrigin = Utilities.FlattenedPos2D(redirectionManager.currPosReal);
        float phys_distance_north = getDistanceInDirectionFromPoint(
            obstaclePolygons, trackingSpacePoints, physOrigin, directions[0]
            );
        float phys_distance_east = getDistanceInDirectionFromPoint(
            obstaclePolygons, trackingSpacePoints, physOrigin, directions[1]
            );
        float phys_distance_west = getDistanceInDirectionFromPoint(
            obstaclePolygons, trackingSpacePoints, physOrigin, directions[2]
            );
    
        // 虚拟场景中Lossers的更新
        Vector2 virt_heading = Utilities.FlattenedDir2D(redirectionManager.currDir);
        List<Vector2> virt_directions = new List<Vector2>
        {
            virt_heading,                               // Forward (north)
            new Vector2(virt_heading.y, -virt_heading.x), // Right (east)
            new Vector2(-virt_heading.y, virt_heading.x)  // Left (west)
        };


        List<List<Vector2>> virtObstacles = null;
        List<Vector2> virtBoundary = null;

        // 获取虚拟场景中的障碍物和边界（暂时为空）   
       //virtObstacles = redirectionManager.globalConfiguration.VirtualObstaclePolygons;
       //virtBoundary = redirectionManager.globalConfiguration.VirtualTrackingSpacePoints;
       virtObstacles = new List<List<Vector2>>();
       virtBoundary = new List<Vector2>();

        // 计算虚拟场景中前/右/左三个方向到最近障碍/边界的距离
        Vector2 virtOrigin = Utilities.FlattenedPos2D(redirectionManager.currPos);
        float virt_distance_north = getDistanceInDirectionFromPoint(
            virtObstacles, virtBoundary, virtOrigin, virt_directions[0] // forward
            );
        float virt_distance_east = getDistanceInDirectionFromPoint(
            virtObstacles, virtBoundary, virtOrigin, virt_directions[1] // right
            );
        float virt_distance_west = getDistanceInDirectionFromPoint(
            virtObstacles, virtBoundary, virtOrigin, virt_directions[2] // left
            );

        // 现在可以用 phys 距离与 virt 距离计算 loss
        cur_north_loss = phys_distance_north - virt_distance_north;
        cur_east_loss = phys_distance_east - virt_distance_east;
        cur_west_loss = phys_distance_west - virt_distance_west;
        // avoid division by zero or infinity
        if (float.IsInfinity(virt_distance_north) || Mathf.Approximately(virt_distance_north, 0f))
            DistanceNorthRate = 1.0f;
        else
            DistanceNorthRate = phys_distance_north / virt_distance_north;


    }

    public void setGain()
    {
        float g_c = 0;          // curvature
        float g_r = 0;          // rotation
        float g_t = 0;          // translation
        float scale = 0;        // scaling factor for curvature gain   
        int cur_direction = 0;  // 1 for west, -1 for east 

        cur_loss = Mathf.Abs(cur_north_loss) + Mathf.Abs(cur_east_loss) + Mathf.Abs(cur_west_loss);

        if (cur_loss < REDIRECTION_LOSS_THRESHOLD) {
            // 如果当前损失值低于阈值，则不进行重定向
            return;
        }

        // 定义旋转增益的最大和最小值
        var deltaDir = redirectionManager.deltaDir;
        var deltaPos = redirectionManager.deltaPos;
        
        // 仅当用户旋转时应用旋转增益
        if (deltaDir != 0) {
            float loss_difference = cur_loss - prev_loss;
            // User is turning in a way that makes the alignment worse. Slow down their turning.
            if (cur_loss > prev_loss) {
                // 源码中的prev_rota_gain = 1.0f
                g_r = redirectionManager.globalConfiguration.MIN_ROT_GAIN * redirectionManager.deltaDir;
            }
            // User is turning in a way that improves the alignment. Speed up their turning.
            else if (cur_loss < prev_loss) {
                g_r = redirectionManager.globalConfiguration.MAX_ROT_GAIN * redirectionManager.deltaDir;
            }
           
            InjectRotation(g_r);
	    }

        // Only apply curvature and translation gains when the user is moving.
        else if(deltaPos.magnitude != 0) {
            // User is moving in a way that makes the alignment worse. Slow down their movement.
            if (cur_west_loss > cur_east_loss)
            {
                scale = Mathf.Min(1.0f, cur_west_loss);
                cur_direction = 1;
            }
            else if (cur_east_loss > cur_west_loss)
            {
                scale = Mathf.Min(1.0f, cur_east_loss);
                cur_direction = -1;
            }           
            
            // Apply Curvature Gain
            float cur_curve_per_deg = 360.0f / (2.0f * Mathf.PI * redirectionManager.globalConfiguration.CURVATURE_RADIUS);
            cur_curve_per_deg = Mathf.Min(cur_curve_per_deg * Math.Abs(scale), cur_curve_per_deg);
            g_c = cur_direction * redirectionManager.deltaPos.magnitude * cur_curve_per_deg;
            InjectCurvature(g_c);

            //  apply Translation Gain
            g_t = Mathf.Clamp(DistanceNorthRate - 1, redirectionManager.globalConfiguration.MIN_TRANS_GAIN, redirectionManager.globalConfiguration.MAX_TRANS_GAIN);
            InjectTranslation(g_t * redirectionManager.deltaPos);
        }

    }

    #region Distance Calculation

    // 计算从origin点沿dir方向到最近障碍物或边界的距离
    public float getDistanceInDirectionFromPoint(List<List<Vector2>> obstacles, List<Vector2> boundary, Vector2 origin, Vector2 dir)
    {
        float maxDistance = 100f; // 设置一个足够大的最大距离       
        float minDistance  = Mathf.Infinity;
        bool hitObstacle = false;

        // 规范化方向向量
        Vector2 normalizedDir = dir.normalized;

        // 1. 先检测障碍物
        if (obstacles != null)
        {
            foreach (var obstacle in obstacles)
            {
                if (obstacle == null || obstacle.Count == 0) continue;
                float distance = RaycastToPolygon(origin, normalizedDir, obstacle, maxDistance);
                if (distance < float.MaxValue && distance < minDistance)
                {
                    minDistance = distance;
                    hitObstacle = true;
                }
            }
        }

        // 如果有障碍物命中，直接返回最小距离
        if (hitObstacle)
            return minDistance;

        // 2. 无障碍物命中，检测边界碰撞
        if (boundary != null && boundary.Count > 0)
        {
            float boundaryDistance = RaycastToPolygon(origin, normalizedDir, boundary, maxDistance);
            if (boundaryDistance < float.MaxValue)
            {
                return boundaryDistance;
            }
        }

        // 3. 没有命中任何物体
        return Mathf.Infinity;

    }

    // 射线与多边形碰撞检测
    private float RaycastToPolygon(Vector2 origin, Vector2 direction, List<Vector2> polygon, float maxDistance)
    {
        if (polygon == null || polygon.Count == 0) return float.MaxValue;

        float minDistance = float.MaxValue;
        // 检查多边形的每条边
        for (int i = 0; i < polygon.Count; i++)
        {
            Vector2 start = polygon[i];
            Vector2 end = polygon[(i + 1) % polygon.Count]; // 循环到第一个点

            float distance = RaycastToLineSegment(origin, direction, start, end, maxDistance);
            if (distance < minDistance)
            {
                minDistance = distance;
            }
        }

        return minDistance;
    }

    // 射线与线段碰撞检测
    private float RaycastToLineSegment(Vector2 origin, Vector2 direction, Vector2 lineStart, Vector2 lineEnd, float maxDistance)
    {
        Vector2 lineVec = lineEnd - lineStart;
        Vector2 lineToOrigin = origin - lineStart;
        
        // 计算叉积
        float cross1 = Cross(lineToOrigin, direction);
        float cross2 = Cross(lineVec, direction);
        
        // 如果射线与线段平行，则没有交点
        if (Mathf.Abs(cross2) < 0.0001f)
            return float.MaxValue;
        
        // 计算射线与线段所在直线的交点参数
        float t1 = Cross(lineVec, lineToOrigin) / cross2;
        float t2 = Vector2.Dot(lineToOrigin, new Vector2(-direction.y, direction.x)) / cross2;
        
        // 检查交点是否在有效范围内
        // t1: 沿射线方向的参数 (距离)
        // t2: 沿线段方向的参数 (0-1表示在线段上)
        if (t1 >= 0 && t2 >= 0 && t2 <= 1 && t1 <= maxDistance)
        {
            return t1;
        }
        
        return float.MaxValue;
    }

    // 二维向量叉积
    private float Cross(Vector2 a, Vector2 b)
    {
        return a.x * b.y - a.y * b.x;
    }
    
    #endregion

}
